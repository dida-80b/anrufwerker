#!/usr/bin/env python3
"""
STT provider registry. Current default remains Whisper HTTP.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Protocol

import aiohttp

logger = logging.getLogger("stt.providers")


class STTProvider(Protocol):
    name: str

    async def transcribe(self, wav_data: bytes) -> str: ...


@dataclass(frozen=True)
class WhisperHttpProvider:
    whisper_url: str
    name: str = "whisper-http"

    async def transcribe(self, wav_data: bytes) -> str:
        form = aiohttp.FormData()
        form.add_field("file", wav_data, filename="audio.wav", content_type="audio/wav")
        form.add_field("language", "de")
        form.add_field("output", "json")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.whisper_url}/inference",
                    data=form,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        logger.error("Whisper HTTP %s", resp.status)
                        return ""
                    result = await resp.json()
                    return (
                        result.get("text", "").strip()
                        if isinstance(result, dict)
                        else ""
                    )
        except Exception as exc:
            logger.error("Whisper HTTP error: %s", exc)
            return ""


def build_stt_registry(whisper_url: str) -> Dict[str, STTProvider]:
    return {"whisper-http": WhisperHttpProvider(whisper_url=whisper_url)}


def get_stt_provider(whisper_url: str, engine: Optional[str] = None) -> STTProvider:
    engine_name = engine or "whisper-http"
    registry = build_stt_registry(whisper_url)
    provider = registry.get(engine_name)
    if provider is None:
        raise ValueError(f"Unsupported STT provider: {engine_name}")
    return provider

