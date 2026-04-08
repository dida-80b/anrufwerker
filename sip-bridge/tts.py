#!/usr/bin/env python3
"""
TTS (Text-to-Speech) — Piper / edge-tts → Asterisk .sln Format.
TTS_ENGINE=piper  → lokaler Piper-HTTP-Service (ONNX)
TTS_ENGINE=edge   → edge-tts (Microsoft Azure Neural, benötigt Internet)
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional

from observability import StepTimer, log_event
from settings import get_setting
from tts_providers import build_tts_registry

logger = logging.getLogger("tts")


async def text_to_asterisk_audio(text: str, voice: str, sounds_dir: Path) -> Path:
    """
    Generate speech from text via edge-tts and convert to
    8kHz mono signed-linear 16-bit (Asterisk native .sln format).
    Returns path to the .sln file.
    """
    file_id = str(uuid.uuid4())
    mp3_path = sounds_dir / f"{file_id}.mp3"
    wav_path = sounds_dir / f"{file_id}.sln"

    # 1. edge-tts: text -> MP3
    proc = await asyncio.create_subprocess_exec(
        "edge-tts",
        "--voice", voice,
        "--text", text,
        "--write-media", str(mp3_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"edge-tts failed: {stderr.decode()}")

    # 2. ffmpeg: MP3 -> 8kHz mono signed-linear 16-bit (Asterisk native .sln format)
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y",
        "-i", str(mp3_path),
        "-ar", "8000",
        "-ac", "1",
        "-af", "volume=10dB",
        "-acodec", "pcm_s16le",
        "-f", "s16le",
        str(wav_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    mp3_path.unlink(missing_ok=True)

    if proc.returncode != 0 or not wav_path.exists():
        raise RuntimeError(f"ffmpeg audio conversion failed: {stderr.decode()}")

    logger.info(f"TTS audio generated: {wav_path}")
    return wav_path


async def generate_tts_mp3(text: str, voice: str, sounds_dir: Path) -> Optional[Path]:
    """
    Erzeugt TTS-Audio. Routing via TTS_ENGINE:
      piper → Piper-HTTP-Service, gibt WAV zurück
      edge  → edge-tts (Microsoft Azure Neural), gibt MP3 zurück
    Alle Formate werden anschließend von convert_to_slin() verarbeitet.
    """
    engine = get_setting("tts_engine", "TTS_ENGINE", "piper")
    registry = build_tts_registry(
        piper_url=get_setting("piper_url", "PIPER_URL", "http://127.0.0.1:5150"),
        piper_voice=get_setting("piper_voice", "PIPER_VOICE", "de_DE-thorsten-high"),
    )
    provider = registry.get(engine, registry["edge"])
    timer = StepTimer(logger, "tts_provider_synthesize", fields={"engine": provider.name})
    audio_path = await provider.synthesize(text, voice, sounds_dir)
    if audio_path is None:
        log_event(logger, "tts_provider_failed", engine=provider.name)
        return None
    timer.emit(path_suffix=audio_path.suffix)
    return audio_path


async def convert_to_slin(audio_path: Path, sample_rate: int = 8000, channels: int = 1) -> Optional[Path]:
    """Convert audio file to SLIN (signed 16-bit linear PCM) for Asterisk. Returns sln path or None."""
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
    """Löscht eine temporäre Audio-Datei."""
    try:
        path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning(f"cleanup failed for {path}: {exc}")
