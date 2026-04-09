#!/usr/bin/env python3
"""
AudioSocket Server for real-time bidirectional voice conversations.

AudioSocket Protocol (Asterisk standard, 3-byte header):
  [1 byte type][2 bytes payload_len BE][payload]
  0x00 = Audio (SLIN 8kHz 16-bit mono, 320 bytes = 20ms)
  0x01 = UUID  (16 binary bytes, sent by Asterisk on connect)
  0x02 = Hangup

Architecture:
  Two concurrent asyncio tasks per connection:
    sender_loop  – reads from send_queue, pads with silence, writes to socket
    receiver_loop – reads from socket, handles UUID/audio/hangup messages
  TTS generation and STT processing run as separate background tasks.
"""

import asyncio
import collections
import json
import logging
import os
import re
import socket as _socket_mod
import sqlite3
import struct
import time
import uuid as uuid_module
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass, field

from audio_utils import is_speech_frame, rms_level, slin_to_wav_bytes
from config import (
    MIN_AUDIO_CHUNK_MS,
    MAX_AUDIO_CHUNK_MS,
    VAD_SPEECH_FRAMES_TO_START,
    VAD_SILENCE_FRAMES_TO_END,
    VAD_RMS_THRESHOLD,
    VAD_BARGE_IN_THRESHOLD,
    VAD_BARGE_IN_FRAMES,
    PREROLL_FRAMES,
    INACTIVITY_TIMEOUT,
    CHECKIN_TIMEOUT,
    MAX_TTS_SECONDS_PER_SENTENCE,
    MAX_TTS_SENTENCES_PER_TURN,
    MAX_TTS_SECONDS_INTRO,
    NO_REGREET_AFTER_INTRO,
    MIN_USER_RMS_PROCESS,
    PROCESS_BUFFERED_DURING_LLM,
    ASYNC_WORKER_QUEUE_DSN,
    ASYNC_WORKER_DISABLED,
)
from observability import log_event
from settings import get_setting, get_setting_bool, get_setting_float, get_setting_int
from stt import transcribe as stt_transcribe
from tts import generate_tts_mp3, convert_to_slin

logger = logging.getLogger("audiosocket")

# Asterisk 18 AudioSocket type bytes (res_audiosocket.c):
#   0x00  remote termination (server sends to end call, or Asterisk treats as fatal)
#   0x01  UUID frame (Asterisk → server, first message only)
#   0x10  audio frame (16-bit 8 kHz SLIN, bidirectional)
KIND_HANGUP = 0x00  # send this to tell Asterisk to terminate
KIND_UUID = 0x01  # receive-only: Asterisk identifies the session
KIND_AUDIO = 0x10  # audio payload – both send and receive

SAMPLE_RATE = 8000
SAMPLE_WIDTH = 2  # 16-bit
CHANNELS = 1
FRAME_SIZE = 320  # 20 ms at 8 kHz 16-bit mono
FRAME_DUR = 0.020  # seconds

SAMPLES_PER_MS = SAMPLE_RATE // 1000

SILENCE_FRAME = bytes(FRAME_SIZE)


@dataclass
class AudioSocketSession:
    uuid: str
    messages: list = field(
        default_factory=list
    )  # Conversation history [{role, content}, ...]
    mission: str = ""  # Current task/mission for this call
    send_queue: object = None  # asyncio.Queue reference for barge-in
    audio_buffer: bytearray = field(default_factory=bytearray)
    last_transcript: str = ""
    processing: bool = False  # guard against concurrent STT tasks
    barge_in_active: bool = (
        False  # True when barge-in has fired → _enqueue_tts skips
    )
    bot_speaking_until: float = 0.0  # timestamp until which the bot is speaking (STT muted)
    last_activity_time: float = field(
        default_factory=time.time
    )  # last user/bot turn
    last_audio_time: float = field(
        default_factory=time.time
    )  # last incoming audio frame
    intro_playing: bool = (
        True  # Barge-in disabled until intro ends (prevents echo hallucination)
    )
    # VAD state
    speech_counter: int = 0
    silence_counter: int = 0
    is_recording: bool = False
    preroll: collections.deque = field(
        default_factory=lambda: collections.deque(maxlen=PREROLL_FRAMES)
    )
    barge_in_saved_audio: list = field(
        default_factory=list
    )  # Saved TTS frames on false barge-in
    # Inbound fields
    direction: str = "outbound"  # "inbound" or "outbound"
    caller_id: str = ""  # Caller's phone number (inbound)
    company: str = ""  # Company name (from company config)
    caller_intent: str = ""  # Detected intent (set after conversation)
    system_prompt_override: str = (
        ""  # Full system prompt (replaces prompt.md for inbound)
    )
    greeting: str = (
        ""  # Exact greeting text from company config (played directly as TTS)
    )


class AudioSocketServer:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9090,
        whisper_url: str = "http://127.0.0.1:8090",
        llm_callback: Optional[Callable[[str, str], Awaitable[str]]] = None,
        tts_voice: str = "de-DE-SeraphinaMultilingualNeural",
        sounds_dir: Path = Path("/sounds"),
        transcripts_dir: Path = Path("/app/data/transcripts"),
        inbound_prompt_fn: Optional[
            Callable
        ] = None,  # caller_id -> {"prompt": str, "company": str}
    ):
        self.host = host
        self.port = port
        self.whisper_url = whisper_url
        self.llm_callback = llm_callback
        self.tts_voice = tts_voice
        self.sounds_dir = sounds_dir
        self.transcripts_dir = transcripts_dir
        self.inbound_prompt_fn = inbound_prompt_fn
        self.sessions: dict[str, AudioSocketSession] = {}
        self._pending_missions: dict[str, str | dict] = {}  # session_uuid → outbound mission (str) or inbound session dict
        self._server_sock: Optional[_socket_mod.socket] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        logger.info(f"STT: Whisper HTTP @ {self.whisper_url}")

    def _setting_int(self, key: str, env_var: str, default: int) -> int:
        return get_setting_int(key, env_var, default)

    def _setting_float(self, key: str, env_var: str, default: float) -> float:
        return get_setting_float(key, env_var, default)

    def _setting_bool(self, key: str, env_var: str, default: bool) -> bool:
        return get_setting_bool(key, env_var, default)

    def _tts_voice(self) -> str:
        return get_setting("tts_voice", "TTS_VOICE", self.tts_voice)

    def _whisper_url(self) -> str:
        return get_setting("whisper_url", "WHISPER_URL", self.whisper_url)

    async def start(self):
        # Use a raw socket + add_reader so we can write silence frames
        # *synchronously* inside the accept callback, before any coroutine runs.
        # asyncio.start_server schedules _handle_connection via create_task, which
        # means at least 2 event-loop iterations pass before we can write anything.
        # Asterisk's non-blocking recv() fires within those iterations → EAGAIN → RST.
        srv = _socket_mod.socket(_socket_mod.AF_INET, _socket_mod.SOCK_STREAM)
        srv.setsockopt(_socket_mod.SOL_SOCKET, _socket_mod.SO_REUSEADDR, 1)
        srv.setblocking(False)
        srv.bind((self.host, self.port))
        srv.listen(100)
        self._server_sock = srv
        self._loop = asyncio.get_running_loop()
        self._loop.add_reader(srv.fileno(), self._sync_accept)
        logger.info(f"AudioSocket server listening on {self.host}:{self.port}")

    async def stop(self):
        if self._server_sock and self._loop:
            self._loop.remove_reader(self._server_sock.fileno())
            self._server_sock.close()
            self._server_sock = None

    # ------------------------------------------------------------------
    # Synchronous accept + silence pre-fill
    # ------------------------------------------------------------------

    def _sync_accept(self):
        """Called synchronously from asyncio's I/O selector callback.

        This runs *inline* inside _run_once, before any other coroutine or
        task gets a chance to run.  We accept the connection and immediately
        push silence frames into the kernel TCP send buffer via sock.send().
        By the time the event loop yields back to Asterisk's recv(), our data
        is already in the buffer → no EAGAIN → no RST.
        """
        try:
            conn, addr = self._server_sock.accept()
        except (BlockingIOError, InterruptedError):
            return

        logger.info(f"[AudioSocket] New connection from {addr}")

        # Disable Nagle: small frames must be sent immediately, not coalesced.
        conn.setsockopt(_socket_mod.IPPROTO_TCP, _socket_mod.TCP_NODELAY, 1)
        # Non-blocking: send() returns immediately; for a fresh connection the
        # kernel send buffer is empty so the full write succeeds at once.
        conn.setblocking(False)

        silence_msg = struct.pack(">BH", KIND_AUDIO, FRAME_SIZE) + SILENCE_FRAME
        try:
            for _ in range(10):  # 10 × 20 ms = 200 ms headroom
                conn.send(silence_msg)
        except (BlockingIOError, InterruptedError):
            pass  # buffer unexpectedly full – rare on new connections
        except Exception as exc:
            logger.error(f"[AudioSocket] Pre-silence write failed: {exc}")
            conn.close()
            return

        self._loop.create_task(self._handle_connection_async(conn, addr))

    async def _handle_connection_async(self, conn: _socket_mod.socket, addr):
        """Wrap raw socket in asyncio StreamReader/Writer, then run handler."""
        # asyncio.open_connection(sock=) creates transport+protocol without
        # calling connect() – correct for a server-side accepted socket.
        reader, writer = await asyncio.open_connection(sock=conn)
        await self._handle_connection(reader, writer, addr)

    # ------------------------------------------------------------------
    # Connection handler
    # ------------------------------------------------------------------

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        addr=None,
    ):
        # addr already logged in _sync_accept; silence already written there too.

        session_uuid: Optional[str] = None
        # Queue of 320-byte SLIN16 chunks to send; sender falls back to silence
        send_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1000)

        # ---- sender task: always running, never blocks the receiver ----
        async def sender_loop():
            while True:
                try:
                    chunk = send_queue.get_nowait()
                except asyncio.QueueEmpty:
                    chunk = SILENCE_FRAME

                if chunk is None:
                    # Hangup signal (e.g. inactivity timeout)
                    logger.info(f"[{session_uuid}] Sending hangup to Asterisk")
                    try:
                        writer.write(struct.pack(">BH", KIND_HANGUP, 0))
                        await writer.drain()
                    except Exception:
                        pass
                    return

                msg = struct.pack(">BH", KIND_AUDIO, FRAME_SIZE) + chunk
                try:
                    writer.write(msg)
                    await writer.drain()
                except Exception as exc:
                    logger.debug(f"[{session_uuid}] Sender closed: {exc}")
                    return

                await asyncio.sleep(FRAME_DUR)

        # ---- receiver task: reads messages, dispatches ----
        async def receiver_loop():
            nonlocal session_uuid

            while True:
                try:
                    header = await reader.readexactly(3)
                except Exception as exc:
                    logger.info(f"[{session_uuid}] Receiver closed: {exc}")
                    return

                kind = header[0]
                payload_len = struct.unpack(">H", header[1:3])[0]
                try:
                    payload = (
                        await reader.readexactly(payload_len)
                        if payload_len > 0
                        else b""
                    )
                except Exception as exc:
                    logger.info(
                        f"[{session_uuid}] Receiver closed reading payload: {exc}"
                    )
                    return

                # Frame-level logging creates high load and audio jitter.
                # Intentionally no per-packet log.

                if kind == KIND_UUID:
                    session_uuid = (
                        str(uuid_module.UUID(bytes=payload))
                        if len(payload) == 16
                        else payload.decode("utf-8", errors="replace")
                        .strip("\x00")
                        .strip()
                    )
                    pending = self._pending_missions.pop(session_uuid, "")

                    # Pending can be str (outbound mission) or dict (inbound session)
                    direction = "outbound"
                    caller_id = ""
                    company = ""
                    system_prompt_override = ""
                    mission = ""
                    greeting = ""
                    if isinstance(pending, dict) and pending.get("type") == "inbound":
                        direction = "inbound"
                        caller_id = pending.get("caller", "")
                        company = pending.get("company", "")
                        system_prompt_override = pending.get("prompt", "")
                        greeting = pending.get("greeting", "")
                        logger.info(
                            f"[{session_uuid}] Inbound call from {caller_id or '(unknown)'} | company: {company}"
                        )
                    else:
                        mission = pending if isinstance(pending, str) else ""

                    session = AudioSocketSession(
                        uuid=session_uuid,
                        mission=mission,
                        send_queue=send_queue,
                        direction=direction,
                        caller_id=caller_id,
                        company=company,
                        system_prompt_override=system_prompt_override,
                        greeting=greeting,
                    )
                    # Mute briefly — echo protection until first TTS audio arrives
                    session.bot_speaking_until = time.time() + 3.0
                    self.sessions[session_uuid] = session
                    log_extra = (
                        f" | mission: {mission[:60]}"
                        if mission
                        else (f" | caller: {caller_id}" if caller_id else "")
                    )
                    logger.info(
                        f"[{session_uuid}] Session started ({direction}){log_extra}"
                    )
                    asyncio.create_task(self._start_session(send_queue, session_uuid))
                    asyncio.create_task(self._inactivity_watchdog(session_uuid))

                elif kind == KIND_AUDIO:
                    if session_uuid:
                        await self._handle_audio(session_uuid, payload, send_queue)

                elif kind == KIND_HANGUP:
                    logger.info(f"[{session_uuid}] Hangup received")
                    return

                else:
                    logger.warning(f"[{session_uuid}] Unknown kind 0x{kind:02x}")

        sender_task = asyncio.create_task(sender_loop())
        receiver_task = asyncio.create_task(receiver_loop())

        try:
            done, pending = await asyncio.wait(
                {sender_task, receiver_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for t in (sender_task, receiver_task):
                t.cancel()
            if session_uuid and session_uuid in self.sessions:
                session = self.sessions.pop(session_uuid)
                if session.messages:
                    self._save_transcript(session)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(f"[{session_uuid}] Connection closed")

    # ------------------------------------------------------------------
    # Audio input handling
    # ------------------------------------------------------------------

    def _is_speech(self, audio_data: bytes, threshold: int = VAD_RMS_THRESHOLD) -> bool:
        """RMS-based speech detection (replaces webrtcvad)."""
        return is_speech_frame(audio_data, threshold)

    async def _handle_audio(
        self,
        session_uuid: str,
        audio_data: bytes,
        send_queue: asyncio.Queue,
    ):
        session = self.sessions.get(session_uuid)
        if not session:
            return

        # Incoming audio frame (for robust inactivity check)
        session.last_audio_time = time.time()
        frame_rms = rms_level(audio_data)

        # Barge-in: always active — even while LLM is processing
        if time.time() < session.bot_speaking_until:
            # Barge-in: user interrupts the bot (higher threshold, more frames needed)
            if frame_rms >= self._setting_int("vad_barge_in_threshold", "VAD_BARGE_IN_THRESHOLD", VAD_BARGE_IN_THRESHOLD):
                session.speech_counter += 1
                if session.speech_counter >= self._setting_int("vad_barge_in_frames", "VAD_BARGE_IN_FRAMES", VAD_BARGE_IN_FRAMES):
                    logger.info(
                        f"[{session_uuid}] Barge-in detected — saving TTS queue for possible resume"
                    )
                    q = session.send_queue
                    saved = []
                    if q:
                        while not q.empty():
                            try:
                                saved.append(q.get_nowait())
                            except Exception:
                                break
                    session.barge_in_saved_audio = saved
                    session.bot_speaking_until = 0.0
                    session.speech_counter = 0
                    session.barge_in_active = True
                    log_event(
                        logger,
                        "barge_in_detected",
                        session_uuid=session_uuid,
                        saved_frames=len(saved),
                        rms=int(frame_rms),
                    )
                    # Ab hier normal weiterverarbeiten (kein return)
                else:
                    return
            else:
                session.speech_counter = 0
                return

        # While LLM is processing: VAD and buffer keep running,
        # but no new STT trigger — audio is still buffered
        if session.processing:
            if frame_rms >= self._setting_int("vad_rms_threshold", "VAD_RMS_THRESHOLD", VAD_RMS_THRESHOLD):
                if (
                    not session.is_recording
                    and session.speech_counter >= self._setting_int("vad_speech_frames_to_start", "VAD_SPEECH_FRAMES_TO_START", VAD_SPEECH_FRAMES_TO_START)
                ):
                    session.is_recording = True
                    for frame in session.preroll:
                        session.audio_buffer.extend(frame)
                    session.preroll.clear()
                if session.is_recording:
                    session.audio_buffer.extend(audio_data)
                session.speech_counter += 1
            else:
                session.preroll.append(bytes(audio_data))
            return

        # RMS-based VAD: check whether frame contains speech
        is_speech = frame_rms >= self._setting_int("vad_rms_threshold", "VAD_RMS_THRESHOLD", VAD_RMS_THRESHOLD)

        if is_speech:
            session.silence_counter = 0
            session.speech_counter += 1
            if (
                not session.is_recording
                and session.speech_counter >= self._setting_int("vad_speech_frames_to_start", "VAD_SPEECH_FRAMES_TO_START", VAD_SPEECH_FRAMES_TO_START)
            ):
                # Speech onset: include preroll buffer retroactively
                session.is_recording = True
                for frame in session.preroll:
                    session.audio_buffer.extend(frame)
                session.preroll.clear()
            if session.is_recording:
                session.audio_buffer.extend(audio_data)
        else:
            session.speech_counter = 0
            session.silence_counter += 1
            if not session.is_recording:
                # Not recording yet: add frame to preroll ring buffer
                session.preroll.append(bytes(audio_data))
            # Silence frames are NOT written to the STT buffer

        # Utterance beenden nach genug Stille
        if (
            session.is_recording
            and session.silence_counter >= self._setting_int("vad_silence_frames_to_end", "VAD_SILENCE_FRAMES_TO_END", VAD_SILENCE_FRAMES_TO_END)
        ):
            if len(session.audio_buffer) > 0:
                session.processing = True
                audio_bytes = bytes(session.audio_buffer)
                session.audio_buffer.clear()
                session.is_recording = False
                session.speech_counter = 0
                session.silence_counter = 0
                session.preroll.clear()
                asyncio.create_task(
                    self._process_audio_task(session, audio_bytes, send_queue)
                )

    # Whisper uses square brackets for non-speech annotations.
    # These are NEVER real user input — Whisper inserts them itself.
    # Words like "Goodbye" or "Thanks" are NOT filtered — the user might actually say them.

    async def _process_audio_task(
        self,
        session: AudioSocketSession,
        audio_bytes: bytes,
        send_queue: asyncio.Queue,
    ):
        def _resume_if_saved():
            """Re-queue saved TTS frames after a false barge-in."""
            saved = session.barge_in_saved_audio
            if not saved:
                return
            session.barge_in_saved_audio = []
            for frame in saved:
                try:
                    send_queue.put_nowait(frame)
                except asyncio.QueueFull:
                    break
            resume_duration = len(saved) * FRAME_DUR + 0.5
            session.bot_speaking_until = time.time() + resume_duration
            log_event(
                logger,
                "barge_in_resumed",
                session_uuid=session.uuid,
                saved_frames=len(saved),
                resume_ms=int(resume_duration * 1000),
            )
            logger.info(
                f"[{session.uuid}] No real input — resuming: {len(saved)} frames ({resume_duration:.1f}s)"
            )

        try:
            # --- Step 1: Does the buffer contain real speech? ---
            # Check RMS across the entire buffer. Line noise sits at ~100–300,
            # real speech at 1000+. Buffer average < 600 → no real content.
            rms = rms_level(audio_bytes)
            min_user_rms = self._setting_int("min_user_rms_process", "MIN_USER_RMS_PROCESS", MIN_USER_RMS_PROCESS)
            if rms < min_user_rms:
                log_event(
                    logger,
                    "turn_skipped_low_rms",
                    session_uuid=session.uuid,
                    rms=int(rms),
                    threshold=min_user_rms,
                )
                logger.info(
                    f"[{session.uuid}] Skipping (RMS {rms:.0f} < {min_user_rms}, probably silence)"
                )
                _resume_if_saved()
                return

            logger.info(
                f"[{session.uuid}] Processing {len(audio_bytes)} bytes (RMS {rms:.0f})"
            )
            log_event(
                logger,
                "turn_processing_started",
                session_uuid=session.uuid,
                audio_bytes=len(audio_bytes),
                rms=int(rms),
            )
            wav_data = self._to_wav(audio_bytes)
            _t_stt = time.time()
            transcript = await self._transcribe(wav_data)
            logger.info(f"[{session.uuid}] ⏱ STT: {(time.time()-_t_stt)*1000:.0f}ms")

            if not transcript or not transcript.strip():
                log_event(logger, "stt_empty", session_uuid=session.uuid)
                logger.info(f"[{session.uuid}] No speech detected")
                _resume_if_saved()
                return

            # --- Step 2: Filter Whisper annotations ---
            # Whisper writes non-speech sounds in square brackets: [Music], [Silence], [Applause]
            transcript = re.sub(r"\[.*?\]", "", transcript).strip()

            if not transcript:
                log_event(logger, "stt_noise_annotation_only", session_uuid=session.uuid)
                logger.info(f"[{session.uuid}] Only noise annotations, skipping")
                _resume_if_saved()
                return

            # Real input detected → discard saved frames
            session.barge_in_saved_audio = []

            if transcript == session.last_transcript:
                log_event(logger, "stt_duplicate", session_uuid=session.uuid)
                logger.info(
                    f"[{session.uuid}] Duplicate transcript, skipping: {transcript}"
                )
                return
            session.last_transcript = transcript
            session.last_activity_time = time.time()
            logger.info(f"[{session.uuid}] Transcript: {transcript}")

            # Append user message to history
            session.messages.append({"role": "user", "content": transcript})

            # Streaming: callback is async generator → TTS sentence-by-sentence in parallel with LLM response
            sentence_count = 0
            response_parts = []
            _t_llm = time.time()
            _llm_first = True
            async for sentence in self._iter_response(
                session.uuid,
                session.messages,
                session.mission,
                session.system_prompt_override,
            ):
                if sentence:
                    if _llm_first:
                        logger.info(f"[{session.uuid}] ⏱ LLM first sentence: {(time.time()-_t_llm)*1000:.0f}ms")
                        _llm_first = False
                    # Phone rule: keep responses short, configurable via ENV.
                    if sentence_count >= self._setting_int("max_tts_sentences_per_turn", "MAX_TTS_SENTENCES_PER_TURN", MAX_TTS_SENTENCES_PER_TURN):
                        break
                    logger.info(
                        f"[{session.uuid}] TTS sentence {sentence_count + 1}: {sentence[:60]}"
                    )
                    log_event(
                        logger,
                        "llm_sentence_ready",
                        session_uuid=session.uuid,
                        sentence_index=sentence_count + 1,
                        text_chars=len(sentence),
                    )
                    await self._enqueue_tts(send_queue, session.uuid, sentence)
                    response_parts.append(sentence)
                    sentence_count += 1

            # Append assistant response to history
            if response_parts:
                session.messages.append(
                    {"role": "assistant", "content": " ".join(response_parts)}
                )
                log_event(
                    logger,
                    "assistant_turn_completed",
                    session_uuid=session.uuid,
                    sentences=len(response_parts),
                    text_chars=sum(len(part) for part in response_parts),
                )

            # Reset dedup after response → user can repeat the same sentence
            session.last_transcript = ""
            logger.info(f"[{session.uuid}] Response done ({sentence_count} sentences)")
        except Exception as exc:
            logger.error(f"[{session.uuid}] Processing error: {exc}")
        finally:
            session.processing = False
            session.barge_in_active = False
            # Optional: immediately process audio buffered during LLM (may increase CPU/latency)
            if (
                self._setting_bool("process_buffered_during_llm", "PROCESS_BUFFERED_DURING_LLM", PROCESS_BUFFERED_DURING_LLM)
                and session.is_recording
                and len(session.audio_buffer) > FRAME_SIZE * self._setting_int("vad_speech_frames_to_start", "VAD_SPEECH_FRAMES_TO_START", VAD_SPEECH_FRAMES_TO_START)
            ):
                buffered = bytes(session.audio_buffer)
                session.audio_buffer.clear()
                session.is_recording = False
                session.speech_counter = 0
                session.silence_counter = 0
                session.preroll.clear()
                logger.info(
                    f"[{session.uuid}] Processing buffered audio from during LLM ({len(buffered)} bytes)"
                )
                session.processing = True
                asyncio.create_task(
                    self._process_audio_task(session, buffered, send_queue)
                )

    # ------------------------------------------------------------------
    # TTS generation → send queue
    # ------------------------------------------------------------------

    # Filter out emojis and non-speakable Unicode symbols
    _EMOJI_RE = re.compile(
        "[\U00010000-\U0010ffff\U0001f300-\U0001f9ff\u2600-\u27bf]+",
        flags=re.UNICODE,
    )
    _MARKDOWN_RE = re.compile(r"\*\[.*?\]\*|\[.*?\]|\*{1,3}|#{1,6}\s?")

    async def _enqueue_tts(
        self,
        send_queue: asyncio.Queue,
        session_uuid: str,
        text: str,
        max_seconds: float = None,
    ):
        """Generate TTS audio and enqueue 320-byte SLIN16 chunks."""
        text = self._EMOJI_RE.sub("", text).strip()
        text = self._MARKDOWN_RE.sub("", text).strip()
        if not text:
            return
        # Suppress re-greeting mid-conversation (configurable)
        session = self.sessions.get(session_uuid)
        if session and self._setting_bool("no_regreet_after_intro", "NO_REGREET_AFTER_INTRO", NO_REGREET_AFTER_INTRO) and len(session.messages) > 1:
            low = text.lower()
            # Only filter genuine second greetings, not farewells.
            if any(g in low for g in ["hello", "hi", "good morning", "good afternoon"]) and not any(
                f in low
                for f in ["goodbye", "bye", "talk soon", "see you"]
            ):
                logger.info(f"[{session_uuid}] Re-greeting filtered: {text[:40]}")
                return
        session = self.sessions.get(session_uuid)
        if session and session.barge_in_active:
            logger.info(
                f"[{session_uuid}] Barge-in active — TTS skipped: {text[:40]}"
            )
            return
        try:
            _t_tts = time.time()
            audio_path = await generate_tts_mp3(text, self._tts_voice(), self.sounds_dir)
            if not audio_path or not audio_path.exists():
                logger.error(f"[{session_uuid}] TTS generation failed")
                return
            logger.info(f"[{session_uuid}] ⏱ TTS gen: {(time.time()-_t_tts)*1000:.0f}ms  ({text[:40]})")

            _t_conv = time.time()
            slin_path = await convert_to_slin(audio_path, SAMPLE_RATE, CHANNELS)
            audio_path.unlink(missing_ok=True)
            if not slin_path or not slin_path.exists():
                logger.error(f"[{session_uuid}] SLIN conversion failed")
                return
            logger.info(f"[{session_uuid}] ⏱ ffmpeg convert: {(time.time()-_t_conv)*1000:.0f}ms")

            with open(slin_path, "rb") as f:
                audio_data = f.read()
            slin_path.unlink(missing_ok=True)

            cap = (
                max_seconds if max_seconds is not None else self._setting_float("max_tts_seconds_per_sentence", "MAX_TTS_SECONDS_PER_SENTENCE", MAX_TTS_SECONDS_PER_SENTENCE)
            )
            max_frames = max(1, int(cap / FRAME_DUR))
            # Measure backlog BEFORE enqueueing — otherwise own frames are counted twice
            queue_delay = send_queue.qsize() * FRAME_DUR
            log_event(
                logger,
                "tts_queue_state",
                session_uuid=session_uuid,
                queued_frames=send_queue.qsize(),
                queue_delay_ms=int(queue_delay * 1000),
            )
            frames = 0
            for i in range(0, len(audio_data), FRAME_SIZE):
                if frames >= max_frames:
                    break
                chunk = audio_data[i : i + FRAME_SIZE]
                if len(chunk) < FRAME_SIZE:
                    chunk = chunk + bytes(FRAME_SIZE - len(chunk))
                await send_queue.put(chunk)
                frames += 1

            # Mute STT for audio duration + queue backlog + echo buffer
            speaking_duration = frames * FRAME_DUR + 0.4
            session = self.sessions.get(session_uuid)
            if session:
                new_until = time.time() + queue_delay + speaking_duration
                # Only extend, never shorten (if multiple sentences follow each other)
                if new_until > session.bot_speaking_until:
                    session.bot_speaking_until = new_until

            # Extend activity timer so the watchdog does not fire during bot response
            if session:
                session.last_activity_time = time.time()
            logger.info(
                f"[{session_uuid}] Enqueued {frames} TTS frames ({speaking_duration:.1f}s muted)"
            )
        except Exception as exc:
            logger.error(f"[{session_uuid}] TTS enqueue error: {exc}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_silence(self, audio_data: bytes, threshold: int = 800) -> bool:
        return rms_level(audio_data) < threshold

    def _to_wav(self, slin_data: bytes) -> bytes:
        return slin_to_wav_bytes(slin_data, SAMPLE_RATE, SAMPLE_WIDTH, CHANNELS)

    # Confidence threshold: avg_logprob below this value → hallucination
    # -0.6 is a good starting point; closer to 0 = stricter, further away = looser
    LOGPROB_THRESHOLD = float(os.getenv("STT_LOGPROB_THRESHOLD", "-1.3"))

    async def _transcribe(self, wav_data: bytes) -> str:
        return await stt_transcribe(wav_data, self._whisper_url())

    async def _iter_response(
        self,
        session_uuid: str,
        messages: list,
        mission: str = "",
        system_prompt: str = "",
    ):
        """Async generator: yields sentences from LLM (streaming) or echo fallback."""
        if self.llm_callback:
            try:
                async for sentence in self.llm_callback(
                    session_uuid, messages, mission, system_prompt
                ):
                    yield sentence
                return
            except Exception as exc:
                logger.error(f"Callback error: {exc}")
        # Echo fallback
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        yield f"You said: {last_user}"

    async def _start_session(self, send_queue: asyncio.Queue, session_uuid: str):
        """The LLM generates the greeting itself — no pre-written intro text."""
        session = self.sessions.get(session_uuid)
        if not session:
            return

        # Greeting: directly from company config (no LLM round-trip) or LLM fallback
        if session.greeting:
            logger.info(f"[{session_uuid}] Intro (config): {session.greeting[:80]}")
            await self._enqueue_tts(
                send_queue,
                session_uuid,
                session.greeting,
                max_seconds=self._setting_float("max_tts_seconds_intro", "MAX_TTS_SECONDS_INTRO", MAX_TTS_SECONDS_INTRO),
            )
            session.messages.append({"role": "assistant", "content": session.greeting})
        else:
            # Outbound / no config greeting: LLM generates the greeting
            trigger = [{"role": "user", "content": "[CALL STARTS]"}]
            logger.info(
                f"[{session_uuid}] Triggering LLM intro (mission: {session.mission[:60]})"
            )
            response_parts = []
            async for sentence in self._iter_response(
                session_uuid, trigger, session.mission, session.system_prompt_override
            ):
                if sentence:
                    if len(response_parts) >= max(1, self._setting_int("max_tts_sentences_per_turn", "MAX_TTS_SENTENCES_PER_TURN", MAX_TTS_SENTENCES_PER_TURN)):
                        break
                    logger.info(f"[{session_uuid}] Intro: {sentence[:60]}")
                    await self._enqueue_tts(
                        send_queue,
                        session_uuid,
                        sentence,
                        max_seconds=self._setting_float("max_tts_seconds_intro", "MAX_TTS_SECONDS_INTRO", MAX_TTS_SECONDS_INTRO),
                    )
                    response_parts.append(sentence)
            if response_parts:
                session.messages.append(
                    {"role": "assistant", "content": " ".join(response_parts)}
                )
            else:
                fallback = "Hello. I am here to help."
                await self._enqueue_tts(send_queue, session_uuid, fallback)
                session.messages.append({"role": "assistant", "content": fallback})

        # Enable barge-in only after the intro has finished playing
        asyncio.create_task(self._clear_intro_flag(session_uuid))

    async def _clear_intro_flag(self, session_uuid: str):
        """Enable barge-in once the intro has finished playing."""
        await asyncio.sleep(0.5)
        session = self.sessions.get(session_uuid)
        if not session:
            return
        while time.time() < session.bot_speaking_until:
            await asyncio.sleep(0.2)
        await asyncio.sleep(0.5)
        if session_uuid in self.sessions:
            session.intro_playing = False
            logger.info(f"[{session_uuid}] Intro done — barge-in enabled")

    async def _inactivity_watchdog(self, session_uuid: str):
        """
        Prompts after CHECKIN_TIMEOUT seconds of silence ("Are you still there?").
        Hangs up after INACTIVITY_TIMEOUT seconds of silence.
        """
        await asyncio.sleep(10)  # kurze Startpause
        checkin_done = False
        while True:
            await asyncio.sleep(5)
            session = self.sessions.get(session_uuid)
            if not session:
                return
            now = time.time()
            idle = now - session.last_activity_time
            idle_audio = now - session.last_audio_time
            inactivity_timeout = self._setting_int("inactivity_timeout", "INACTIVITY_TIMEOUT", INACTIVITY_TIMEOUT)
            checkin_timeout = self._setting_int("checkin_timeout", "CHECKIN_TIMEOUT", CHECKIN_TIMEOUT)
            if idle >= inactivity_timeout:
                logger.info(
                    f"[{session_uuid}] Inactivity timeout ({idle:.0f}s) — hanging up"
                )
                if session.send_queue:
                    await session.send_queue.put(None)
                return
            # Check-in only on real silence:
            # - no user/bot turn since CHECKIN_TIMEOUT
            # - no incoming audio frame since CHECKIN_TIMEOUT
            # - bot is not currently speaking
            if (
                idle >= checkin_timeout
                and idle_audio >= checkin_timeout
                and now >= session.bot_speaking_until
                and not checkin_done
                and not session.processing
            ):
                checkin_done = True
                logger.info(f"[{session_uuid}] Silence {idle:.0f}s — LLM check-in")
                # Inject silence as user message → LLM responds contextually
                session.messages.append(
                    {"role": "user", "content": f"[SILENCE: {int(idle)} seconds]"}
                )
                response_parts = []
                async for sentence in self._iter_response(
                    session_uuid,
                    session.messages,
                    session.mission,
                    session.system_prompt_override,
                ):
                    if sentence:
                        await self._enqueue_tts(
                            session.send_queue, session_uuid, sentence
                        )
                        response_parts.append(sentence)
                if response_parts:
                    session.messages.append(
                        {"role": "assistant", "content": " ".join(response_parts)}
                    )
            # Reset check-in when activity resumes
            if idle < checkin_timeout:
                checkin_done = False

    def _save_transcript(self, session: AudioSocketSession):
        """Save conversation history as JSON to disk."""
        import json as _json_mod
        from datetime import datetime as _dt, timezone as _tz

        try:
            transcript_dir = self.transcripts_dir
            transcript_dir.mkdir(parents=True, exist_ok=True)
            ts = _dt.now(_tz.utc).strftime("%Y%m%d_%H%M%S")
            path = transcript_dir / f"{ts}_{session.uuid}.json"
            data = {
                "session_uuid": session.uuid,
                "timestamp": _dt.now(_tz.utc).isoformat(),
                "direction": session.direction,
                "company": session.company,
                "caller_id": session.caller_id,
                "caller_intent": session.caller_intent,
                "mission": session.mission,
                "turn_count": len([m for m in session.messages if m["role"] == "user"]),
                "messages": session.messages,
            }
            path.write_text(_json_mod.dumps(data, ensure_ascii=False, indent=2))
            logger.info(f"[{session.uuid}] Transcript saved: {path.name}")
            self._enqueue_async_worker(data)
        except Exception as exc:
            logger.error(f"[{session.uuid}] Failed to save transcript: {exc}")

    def _enqueue_async_worker(self, transcript_data: dict):
        """Insert a job into the async-worker SQLite queue."""
        if ASYNC_WORKER_DISABLED:
            return
        try:
            db_path = ASYNC_WORKER_QUEUE_DSN
            if not db_path:
                return
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    call_id TEXT UNIQUE NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            now = datetime.now(timezone.utc).isoformat()
            payload = json.dumps(transcript_data, ensure_ascii=False)
            conn.execute(
                "INSERT OR IGNORE INTO jobs (call_id, payload, status, created_at, updated_at) VALUES (?, ?, 'queued', ?, ?)",
                (transcript_data["session_uuid"], payload, now, now),
            )
            conn.commit()
            conn.close()
            logger.info(
                f"[{transcript_data['session_uuid']}] Async-worker job enqueued"
            )
        except Exception as exc:
            logger.error(
                f"[{transcript_data.get('session_uuid', '?')}] Failed to enqueue async-worker job: {exc}"
            )
