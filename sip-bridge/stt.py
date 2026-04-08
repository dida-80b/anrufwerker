#!/usr/bin/env python3
"""
STT (Speech-to-Text) — Whisper HTTP (GPU).

Transcribes audio via the whisper.cpp HTTP server.
On error, "" is returned — the call stays active and the turn is skipped.
"""

import logging
import time

from observability import log_event
from settings import get_setting
from stt_providers import get_stt_provider

logger = logging.getLogger("stt")


async def transcribe(wav_data: bytes, whisper_url: str) -> str:
    """
    Transcribe WAV audio via Whisper HTTP (GPU).

    Args:
        wav_data:    Raw WAV bytes (8 kHz or 16 kHz, 16-bit mono)
        whisper_url: URL of the whisper.cpp HTTP server (e.g. http://127.0.0.1:8090)

    Returns:
        Transcribed text, or "" on error / silence.
    """
    provider = get_stt_provider(
        whisper_url,
        get_setting("stt_engine", "STT_ENGINE", "whisper-http"),
    )
    t0 = time.monotonic()
    text = await provider.transcribe(wav_data)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    log_event(
        logger,
        "stt_transcribe",
        engine=provider.name,
        latency_ms=elapsed_ms,
        text_chars=len(text),
    )
    if text:
        logger.info("Whisper (%sms): '%s'", elapsed_ms, text[:80])
    return text
