#!/usr/bin/env python3
"""
Piper TTS HTTP Service
======================
Lädt alle .onnx-Modelle aus /voices beim Start.
POST /synthesize  →  WAV-Audio (22050 Hz mono, 16-bit PCM)
GET  /voices      →  Liste der geladenen Stimmen
GET  /health      →  {"status": "ok"}
"""

import io
import logging
import os
import wave
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("piper-server")

VOICES_DIR = Path(os.getenv("VOICES_DIR", "/voices"))
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "5150"))

# ── ONNX provider selection ────────────────────────────────────────────────
# ROCm: onnxruntime-rocm stellt "ROCMExecutionProvider" bereit.
# Fallback: CPU. HSA_OVERRIDE_GFX_VERSION für gfx1100 (RX 7900 XT).
def _get_onnx_providers() -> list:
    try:
        import onnxruntime as ort
        available = ort.get_available_providers()
        for ep in ("ROCMExecutionProvider", "MIGraphXExecutionProvider"):
            if ep in available:
                logger.info(f"ONNX: using {ep}")
                return [ep, "CPUExecutionProvider"]
    except Exception:
        pass
    logger.info("ONNX: using CPUExecutionProvider")
    return ["CPUExecutionProvider"]


ONNX_PROVIDERS = _get_onnx_providers()

# ── Voice registry ─────────────────────────────────────────────────────────
loaded_voices: dict = {}   # name → PiperVoice instance


def _load_all_voices():
    from piper import PiperVoice

    if not VOICES_DIR.exists():
        logger.warning(f"Voices dir not found: {VOICES_DIR}")
        return

    for onnx_path in sorted(VOICES_DIR.glob("*.onnx")):
        name = onnx_path.stem  # e.g. de_DE-thorsten-high
        json_path = onnx_path.with_suffix(".onnx.json")
        if not json_path.exists():
            logger.warning(f"Missing config for {onnx_path.name}, skipping")
            continue
        try:
            use_cuda = any("ROCM" in p or "CUDA" in p for p in ONNX_PROVIDERS)
            voice = PiperVoice.load(str(onnx_path), config_path=str(json_path), use_cuda=use_cuda)
            loaded_voices[name] = voice
            logger.info(f"Loaded voice: {name}")
        except Exception as exc:
            logger.error(f"Failed to load {name}: {exc}")


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int, channels: int = 1, sampwidth: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


# ── FastAPI app ────────────────────────────────────────────────────────────
app = FastAPI(title="Piper TTS", version="1.0.0")


class SynthRequest(BaseModel):
    text: str
    voice: Optional[str] = None


@app.on_event("startup")
async def startup():
    _load_all_voices()
    logger.info(f"Piper ready — {len(loaded_voices)} voice(s): {list(loaded_voices)}")


@app.get("/health")
def health():
    return {"status": "ok", "voices": list(loaded_voices)}


@app.get("/voices")
def voices():
    return {"voices": list(loaded_voices)}


@app.post("/synthesize")
def synthesize(req: SynthRequest):
    voice_name = req.voice or DEFAULT_VOICE or (list(loaded_voices)[0] if loaded_voices else None)
    if not voice_name:
        raise HTTPException(503, "No voices loaded")

    voice = loaded_voices.get(voice_name)
    if not voice:
        # fuzzy: contains match
        for k in loaded_voices:
            if voice_name in k or k in voice_name:
                voice = loaded_voices[k]
                voice_name = k
                break
    if not voice:
        raise HTTPException(404, f"Voice '{req.voice}' not found. Available: {list(loaded_voices)}")

    try:
        buf = io.BytesIO()
        first_chunk = None
        pcm_parts = []
        for chunk in voice.synthesize(req.text):
            if first_chunk is None:
                first_chunk = chunk
            pcm_parts.append(chunk.audio_int16_bytes)
        if not first_chunk or not pcm_parts:
            raise ValueError("No audio generated")
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(first_chunk.sample_channels)
            wf.setsampwidth(first_chunk.sample_width)
            wf.setframerate(first_chunk.sample_rate)
            for pcm in pcm_parts:
                wf.writeframes(pcm)
        wav_bytes = buf.getvalue()
        return Response(content=wav_bytes, media_type="audio/wav")
    except Exception as exc:
        logger.error(f"Synthesis failed: {exc}")
        raise HTTPException(500, f"Synthesis error: {exc}")


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
