#!/usr/bin/env python3
"""
STT (Speech-to-Text) — Whisper HTTP (GPU).

Transkribiert Audio via whisper.cpp HTTP Server der auf der RX 7900 XTX läuft.
Bei Fehler wird "" zurückgegeben — der Anruf bleibt aktiv, der Turn wird übersprungen.
"""

import logging
import time

from observability import log_event
from settings import get_setting
from stt_providers import get_stt_provider

logger = logging.getLogger("stt")


async def transcribe(wav_data: bytes, whisper_url: str) -> str:
    """
    Transkribiert WAV-Audio via Whisper HTTP (GPU).

    Args:
        wav_data:    Rohe WAV-Bytes (8kHz oder 16kHz, 16-bit mono)
        whisper_url: URL des whisper.cpp HTTP Servers (z.B. http://127.0.0.1:8090)

    Returns:
        Transkribierter Text oder "" bei Fehler/Stille.
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
