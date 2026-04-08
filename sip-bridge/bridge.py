#!/usr/bin/env python3
"""
SIP Bridge
==========
Verbindet Asterisk/Fritz!Box mit einem lokalen Whisper-STT + Ollama-LLM + edge-TTS.

Architektur:
  Telefonnetz → Fritz!Box → Asterisk (SIP) → AudioSocket → sip-bridge
    → Whisper (STT) → Ollama (LLM) → edge-tts (TTS) → Asterisk → Telefon

Eingehender Anruf:
  1. Anruf kommt über Fritz!Box → Asterisk per SIP
  2. Asterisk schickt StasisStart-Event über ARI WebSocket an die Bridge
  3. Bridge beantwortet den Channel und registriert die Inbound-Session
  4. Asterisk verbindet den Channel mit dem AudioSocket-Server (bidirektionales Audio)
  5. AudioSocket-Session: STT → Ollama → TTS in Echtzeit

Ausgehender Anruf:
  1. POST /call mit Zielrufnummer und Mission
  2. Bridge originiiert Anruf via ARI (Asterisk → Fritz!Box → PSTN)
  3. Asterisk verbindet bei Annahme mit AudioSocket-Session
"""

import asyncio
import aiohttp
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional, Dict

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse

from config import (
    ASTERISK_HOST,
    ASTERISK_ARI_PORT,
    ASTERISK_ARI_USER,
    ASTERISK_ARI_PASS,
    BRIDGE_PORT,
    SOUNDS_DIR,
    TRANSCRIPTS_PATH,
    TTS_VOICE,
    AUDIOSOCKET_PORT,
    WHISPER_URL,
    INBOUND_ENABLED,
    COMPANY_CONFIG_PATH,
    company_config,
    LOG_LEVEL,
    PROMPT_INBOUND_MD,
)
from llm import stream_response, build_system_prompt
from settings import load_company_config, seed_from_config, seed_runtime_settings, seed_system_prompt
from tts import text_to_asterisk_audio
from audiosocket import AudioSocketServer

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("bridge")

ARI_BASE = f"http://{ASTERISK_HOST}:{ASTERISK_ARI_PORT}/ari"
ARI_AUTH = aiohttp.BasicAuth(ASTERISK_ARI_USER, ASTERISK_ARI_PASS)

SOUNDS_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# State
# ============================================================

# channel_id -> call info dict
active_calls: Dict[str, Dict] = {}

# AudioSocket server instance
audiosocket_server: Optional[AudioSocketServer] = None

app = FastAPI(title="SIP Bridge", version="0.3.0")

# ============================================================
# ARI HTTP helpers
# ============================================================

async def ari_get(path: str) -> Dict:
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{ARI_BASE}{path}", auth=ARI_AUTH) as r:
            return await r.json()

async def ari_post(path: str, params: Dict = None, json_data: Dict = None) -> Dict:
    async with aiohttp.ClientSession() as s:
        async with s.post(
            f"{ARI_BASE}{path}", auth=ARI_AUTH,
            params=params or {}, json=json_data
        ) as r:
            try:
                return await r.json()
            except Exception:
                return {"status": r.status}

async def ari_post_form(path: str, form_data: aiohttp.FormData) -> Dict:
    async with aiohttp.ClientSession() as s:
        async with s.post(
            f"{ARI_BASE}{path}", auth=ARI_AUTH,
            data=form_data
        ) as r:
            try:
                return await r.json()
            except Exception:
                return {"status": r.status}

async def ari_delete(path: str) -> Dict:
    async with aiohttp.ClientSession() as s:
        async with s.delete(f"{ARI_BASE}{path}", auth=ARI_AUTH) as r:
            try:
                return await r.json()
            except Exception:
                return {}

async def answer_channel(channel_id: str):
    await ari_post(f"/channels/{channel_id}/answer")
    logger.info(f"[{channel_id}] Answered")

async def hangup_channel(channel_id: str):
    await ari_delete(f"/channels/{channel_id}")
    logger.info(f"[{channel_id}] Hung up")

async def play_audio_on_channel(channel_id: str, wav_path: Path) -> str:
    """
    Play an audio file on a channel via ARI.
    Asterisk fetches the file directly over HTTP from the bridge server.
    Returns playback ID.
    """
    playback_id = str(uuid.uuid4())

    if not wav_path.exists():
        logger.error(f"[{channel_id}] Audio file not found: {wav_path}")
        return playback_id

    result = await ari_post(
        f"/channels/{channel_id}/play/{playback_id}",
        params={"media": f"sound:custom/{wav_path.stem}"}
    )
    logger.info(f"[{channel_id}] Playing sound:custom/{wav_path.stem} -> {result}")
    return playback_id

async def wait_for_playback(channel_id: str, playback_id: str, timeout: float = 30.0):
    """Wait until a playback finishes (via event or timeout)."""
    call = active_calls.get(channel_id)
    if not call:
        return

    event = asyncio.Event()
    call.setdefault("playback_events", {})[playback_id] = event
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"[{channel_id}] Playback {playback_id} timed out")

# ============================================================
# Helpers
# ============================================================

def normalize_for_fritzbox(number: str) -> str:
    """
    Normalize a phone number for dialing via Fritz!Box.
    +49 country code -> leading 0
    """
    number = number.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if number.startswith("+49"):
        number = "0" + number[3:]
    elif number.startswith("0049"):
        number = "0" + number[4:]
    elif number.startswith("49") and len(number) > 10:
        number = "0" + number[2:]
    return number

# ============================================================
# ARI WebSocket event handler
# ============================================================

async def handle_ari_event(event: Dict):
    etype = event.get("type", "")

    if etype == "StasisStart":
        channel    = event["channel"]
        channel_id = channel["id"]
        args       = event.get("args", [])
        is_outbound = "outbound" in args

        caller = channel.get("caller", {}).get("number", "unknown")
        called = channel.get("dialplan", {}).get("exten", "unknown")

        logger.info(f"[{channel_id}] Call started | {caller} -> {called} | outbound={is_outbound}")

        # Merge with pre-existing state (outbound calls store webhook_url before connecting)
        existing = active_calls.get(channel_id, {})
        active_calls[channel_id] = {
            "channel_id": channel_id,
            "is_outbound": is_outbound,
            "caller": existing.get("caller", caller),
            "called": existing.get("called", called),
            "webhook_url": existing.get("webhook_url", OPENCLAW_INCOMING),
            "playback_events": {},
        }

        if is_outbound:
            logger.info(f"[{channel_id}] Outbound call initiated, waiting for remote to answer")
            return

        await answer_channel(channel_id)

    elif etype == "ChannelStateChange":
        channel_id = event["channel"]["id"]
        state = event["channel"].get("state", "")
        logger.info(f"[{channel_id}] ChannelStateChange -> {state}")

    elif etype == "StasisEnd":
        channel_id = event["channel"]["id"]
        logger.info(f"[{channel_id}] Call ended")
        active_calls.pop(channel_id, None)

    elif etype == "ChannelDtmfReceived":
        channel_id = event["channel"]["id"]
        digit = event.get("digit", "")
        logger.info(f"[{channel_id}] DTMF: {digit}")

        call = active_calls.get(channel_id)
        if call:
            call["dtmf_buffer"] = call.get("dtmf_buffer", "") + digit
            num_digits = call.get("dtmf_num_digits")
            if "dtmf_event" in call:
                if digit == "#" or (num_digits and len(call["dtmf_buffer"]) >= num_digits):
                    call["dtmf_event"].set()

    elif etype == "PlaybackFinished":
        playback_id = event.get("playback", {}).get("id", "")
        channel_id  = event.get("playback", {}).get("target_uri", "").replace("channel:", "")
        logger.info(f"[{channel_id}] Playback finished: {playback_id}")

        call = active_calls.get(channel_id, {})
        events = call.get("playback_events", {})
        if playback_id in events:
            events[playback_id].set()

    elif etype in ("ChannelDestroyed", "ChannelHangupRequest"):
        channel_id = event.get("channel", {}).get("id", "")
        active_calls.pop(channel_id, None)


async def ari_websocket_listener():
    """
    Maintain a persistent WebSocket connection to Asterisk ARI.
    Reconnects automatically on disconnect.
    """
    ws_url = (
        f"ws://{ASTERISK_HOST}:{ASTERISK_ARI_PORT}/ari/events"
        f"?app=anrufwerker-bridge&subscribeAll=true"
    )
    while True:
        try:
            logger.info(f"Connecting to ARI WebSocket: {ws_url}")
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    ws_url, auth=ARI_AUTH, heartbeat=30
                ) as ws:
                    logger.info("ARI WebSocket connected")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                event = json.loads(msg.data)
                                await handle_ari_event(event)
                            except json.JSONDecodeError as e:
                                logger.error(f"JSON decode error: {e}")
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                            logger.warning("ARI WebSocket closed")
                            break
        except Exception as e:
            logger.error(f"ARI WebSocket error: {e}")
        logger.info("Reconnecting to ARI in 5s...")
        await asyncio.sleep(5)

# ============================================================
# Startup
# ============================================================

@app.on_event("startup")
async def startup():
    global audiosocket_server

    logger.info("=" * 50)
    logger.info("SIP Bridge starting up")
    logger.info(f"  Asterisk ARI: {ARI_BASE}")
    logger.info(f"  Bridge port:  {BRIDGE_PORT}")
    logger.info(f"  AudioSocket port: {AUDIOSOCKET_PORT}")
    logger.info(f"  Whisper URL:  {WHISPER_URL}")
    logger.info(f"  Sounds dir:   {SOUNDS_DIR}")
    logger.info(f"  TTS voice:    {TTS_VOICE}")
    logger.info("=" * 50)

    # DB mit Defaults aus JSON-Config + prompt_inbound.md befüllen (INSERT OR IGNORE)
    seed_runtime_settings()
    seed_from_config(company_config)
    seed_system_prompt(PROMPT_INBOUND_MD)

    if INBOUND_ENABLED:
        cfg = load_company_config()
        if cfg.get("company_name"):
            logger.info(f"  ** INBOUND AI ENABLED ** Company: {cfg['company_name']}")
        else:
            logger.warning("  INBOUND_ENABLED=true aber kein company_name in DB/Config!")

    # Inbound prompt builder — liest DB pro Anruf (live-updatebar ohne Restart)
    inbound_fn = None
    if INBOUND_ENABLED:
        inbound_fn = lambda cid: build_system_prompt(load_company_config(), cid)

    # Start ARI WebSocket listener
    asyncio.create_task(ari_websocket_listener())

    # Start AudioSocket server for bidirectional voice
    audiosocket_server = AudioSocketServer(
        host="0.0.0.0",
        port=AUDIOSOCKET_PORT,
        whisper_url=WHISPER_URL,
        llm_callback=stream_response,
        tts_voice=TTS_VOICE,
        sounds_dir=SOUNDS_DIR,
        transcripts_dir=TRANSCRIPTS_PATH,
        inbound_prompt_fn=inbound_fn,
    )
    await audiosocket_server.start()


if __name__ == "__main__":
    uvicorn.run(
        "bridge:app",
        host=os.getenv("BRIDGE_HOST", "0.0.0.0"),
        port=BRIDGE_PORT,
        log_level="info",
        reload=False,
        loop="asyncio",  # Disable uvloop: pure asyncio Transport.write() calls
                         # sock.send() synchronously on empty buffer, ensuring
                         # Asterisk's first recv() on its non-blocking socket succeeds.
    )

# ============================================================
# REST Endpoints
# ============================================================

@app.get("/health")
async def health():
    return {
        "status":       "ok",
        "active_calls": len(active_calls),
        "asterisk":     f"{ASTERISK_HOST}:{ASTERISK_ARI_PORT}",
    }


@app.get("/sounds/{filename}")
async def serve_sound(filename: str):
    from fastapi.responses import FileResponse
    from fastapi import HTTPException
    path = SOUNDS_DIR / Path(filename).name
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path)


@app.get("/inbound/register")
async def inbound_register(uuid: str, caller: str = ""):
    """
    Wird von Asterisk per CURL vor dem AudioSocket-Connect aufgerufen.
    Registriert die inbound Session mit Caller-ID und Company-Prompt.
    """
    if not audiosocket_server:
        return JSONResponse({"status": "error", "msg": "AudioSocket not running"}, status_code=503)
    cfg = load_company_config()
    if not cfg.get("company_name"):
        logger.warning(f"[inbound] Register called but no company_name in DB/Config (uuid={uuid})")
        return JSONResponse({"status": "no_config"})

    result = build_system_prompt(cfg, caller)
    audiosocket_server._pending_missions[uuid] = {
        "type": "inbound",
        "caller": caller,
        "prompt": result.get("prompt", ""),
        "company": result.get("company", ""),
        "greeting": result.get("greeting", ""),
    }
    logger.info(f"[inbound] Registered UUID={uuid} caller={caller or '(unbekannt)'} company={result.get('company', '')}")
    return {"status": "ok", "uuid": uuid, "caller": caller}


@app.get("/transcripts")
async def list_transcripts():
    """Listet alle gespeicherten Gesprächs-Transcripts."""
    transcript_dir = TRANSCRIPTS_PATH
    if not transcript_dir.exists():
        return {"transcripts": []}
    files = sorted(transcript_dir.glob("*.json"), reverse=True)
    result = []
    for f in files[:50]:  # max 50 neueste
        try:
            data = json.loads(f.read_text())
            result.append({
                "file": f.name,
                "session_uuid": data.get("session_uuid"),
                "timestamp": data.get("timestamp"),
                "mission": data.get("mission", "")[:80],
                "turn_count": data.get("turn_count", 0),
            })
        except Exception:
            pass
    return {"transcripts": result}


@app.get("/transcripts/{filename}")
async def get_saved_transcript(filename: str):
    """Liest einen gespeicherten Transcript."""
    path = TRANSCRIPTS_PATH / Path(filename).name
    if not path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return json.loads(path.read_text())


@app.get("/call/{session_uuid}/transcript")
async def get_transcript(session_uuid: str):
    """Gibt die vollständige Gesprächshistorie einer laufenden Session zurück."""
    if not audiosocket_server:
        return JSONResponse({"error": "AudioSocket server not running"}, status_code=503)
    session = audiosocket_server.sessions.get(session_uuid)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return {
        "session_uuid": session_uuid,
        "mission": session.mission,
        "messages": session.messages,
        "turn_count": len([m for m in session.messages if m["role"] == "user"]),
    }


@app.post("/call/{session_uuid}/instruct")
async def instruct_session(session_uuid: str, mission: str = Form(...)):
    """
    Setzt eine neue Mission/Aufgabe für eine laufende Session.
    Die neue Aufgabe wird ab dem nächsten User-Turn aktiv.
    """
    if not audiosocket_server:
        return JSONResponse({"error": "AudioSocket server not running"}, status_code=503)
    session = audiosocket_server.sessions.get(session_uuid)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    old_mission = session.mission
    session.mission = mission
    logger.info(f"[{session_uuid}] Mission updated: {mission[:80]}")
    return {"status": "ok", "session_uuid": session_uuid, "mission": mission, "previous_mission": old_mission}


@app.get("/calls")
async def list_active_calls():
    """Listet alle aktiven Anrufe (laufende AudioSocket-Sessions + klingende Channels)."""
    result = []

    # Laufende Gespraeche (AudioSocket-Sessions)
    if audiosocket_server:
        for uuid, session in audiosocket_server.sessions.items():
            result.append({
                "session_uuid": uuid,
                "status": "active",
                "mission": session.mission[:80] if session.mission else "",
                "turn_count": len([m for m in session.messages if m["role"] == "user"]),
                "idle_seconds": round(time.time() - session.last_activity_time, 1),
            })

    # Klingende / verbindende Channels ohne AudioSocket-Session
    for channel_id, call in active_calls.items():
        result.append({
            "channel_id": channel_id,
            "status": "ringing",
            "caller": call.get("caller", ""),
            "called": call.get("called", ""),
            "is_outbound": call.get("is_outbound", False),
        })

    return {"calls": result, "total": len(result)}


@app.post("/call")
async def create_call_endpoint(
    to: str = Form(...),
    from_: str = Form(None, alias="From"),
    mission: str = Form(""),
):
    """
    Initiiert einen ausgehenden Anruf via AudioSocket.
    mission = Aufgabe/Mitteilung für den Bot (wird in den System-Prompt eingebettet).
    Der LLM startet das Gespräch selbst — kein vorgefertigter Intro-Text.
    """
    content = mission  # intern weiter als content/mission verwendet
    logger.info(f"Call request: {from_} -> {to} | mission={mission[:80]}")

    to_normalized = normalize_for_fritzbox(to)
    caller_id = from_ or os.getenv("FRITZBOX_PHONE_NUMBER", "")
    session_uuid = str(uuid.uuid4())

    try:
        result = await ari_post("/channels/originate", json_data={
            "endpoint": f"PJSIP/{to_normalized}@fritzbox",
            "context": "audiosocket-conversation",
            "extension": "s",
            "priority": 1,
            "callerId": f'"{caller_id}" <{caller_id}>',
            "timeout": 30,
            "variables": {"AUDIOSOCKET_UUID": session_uuid},
        })
        logger.info(f"Originate result: {result}")

        if audiosocket_server and content:
            audiosocket_server._pending_missions[session_uuid] = content
            logger.info(f"[{session_uuid}] Mission: {content[:80]}")

    except Exception as e:
        logger.error(f"Call failed: {e}")
        return JSONResponse({"message": str(e)}, status_code=500)

    call_sid = session_uuid.replace("-", "")
    return JSONResponse({
        "sid": call_sid,
        "status": "ringing",
        "to": to,
        "from": caller_id,
        "session_uuid": session_uuid,
    }, status_code=201)


@app.delete("/call/{session_uuid}")
async def hangup_call(session_uuid: str):
    """Beendet einen laufenden Anruf sofort (sendet Hangup an Asterisk)."""
    if not audiosocket_server:
        return JSONResponse({"error": "AudioSocket server not running"}, status_code=503)

    session = audiosocket_server.sessions.get(session_uuid)
    if not session or not session.send_queue:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    # None in die Queue → sender_loop erkennt Hangup-Signal und sendet KIND_HANGUP (0x00) an Asterisk
    await session.send_queue.put(None)
    logger.info(f"[{session_uuid}] Hangup requested via API")
    return {"status": "hanging_up", "session_uuid": session_uuid}


@app.get("/audiosocket/status")
async def audiosocket_status():
    """Get AudioSocket server status."""
    running = bool(audiosocket_server and getattr(audiosocket_server, "_server_sock", None))
    return {
        "status": "running" if running else "stopped",
        "active_sessions": len(audiosocket_server.sessions) if audiosocket_server else 0,
        "port": AUDIOSOCKET_PORT,
        "whisper_url": WHISPER_URL,
    }
