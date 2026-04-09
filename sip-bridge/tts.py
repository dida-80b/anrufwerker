#!/usr/bin/env python3
"""
TTS (Text-to-Speech) — Piper / edge-tts → Asterisk .sln format.

TTS_ENGINE=piper  → local Piper HTTP service (ONNX), uses TTS_URL + TTS_VOICE
TTS_ENGINE=edge   → edge-tts (Microsoft Azure Neural, requires internet), uses TTS_VOICE

Both engines read their config from the DB/env at call time — no restart needed when
settings change.
"""

import logging
from pathlib import Path
from typing import Optional

from observability import StepTimer, log_event
from settings import get_setting
from tts_providers import build_tts_registry

logger = logging.getLogger("tts")


async def generate_tts_mp3(text: str, voice: str, sounds_dir: Path) -> Optional[Path]:
    """
    Generate TTS audio. Routed via tts_engine:
      piper → Piper HTTP service (tts_url/synthesize), returns WAV
      edge  → edge-tts (Microsoft Azure Neural), returns MP3
    All formats are then processed by convert_to_slin().

    The voice parameter is the active TTS voice (from settings/session).
    For HTTP engines it is sent in the request payload; for edge it is the CLI argument.
    """
    engine = get_setting("tts_engine", "TTS_ENGINE", "piper")
    tts_url = get_setting("tts_url", "TTS_URL", "http://127.0.0.1:5150")
    registry = build_tts_registry(tts_url=tts_url)

    if engine not in registry:
        logger.warning(
            "Unknown TTS engine %r — falling back to 'piper'. Valid: %s",
            engine, list(registry),
        )
        engine = "piper"

    provider = registry[engine]
    timer = StepTimer(logger, "tts_provider_synthesize", fields={"engine": provider.name})
    audio_path = await provider.synthesize(text, voice, sounds_dir)
    if audio_path is None:
        log_event(logger, "tts_provider_failed", engine=provider.name)
        return None
    timer.emit(path_suffix=audio_path.suffix)
    return audio_path


async def convert_to_slin(audio_path: Path, sample_rate: int = 8000, channels: int = 1) -> Optional[Path]:
    """Convert audio file to SLIN (signed 16-bit linear PCM) for Asterisk. Returns sln path or None."""
    import asyncio
    slin_path = audio_path.with_suffix(".sln")
    timer = StepTimer(
        logger,
        "tts_convert_to_slin",
        fields={"sample_rate": sample_rate, "channels": channels},
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", str(audio_path),
            "-ar", str(sample_rate),
            "-ac", str(channels),
            "-af", "aresample=resampler=soxr:precision=28,highpass=f=80",
            "-f", "s16le",
            str(slin_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0 or not slin_path.exists():
            logger.error(f"ffmpeg failed: {stderr.decode()}")
            return None
        timer.emit(path_suffix=slin_path.suffix)
        return slin_path
    except Exception as exc:
        logger.error(f"Conversion error: {exc}")
        return None


def cleanup(path: Path):
    """Delete a temporary audio file."""
    try:
        path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning(f"cleanup failed for {path}: {exc}")
