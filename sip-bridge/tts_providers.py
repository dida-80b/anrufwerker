#!/usr/bin/env python3
"""
TTS provider registry for the active engine set.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Protocol

import aiohttp

logger = logging.getLogger("tts.providers")


class TTSProvider(Protocol):
    name: str

    async def synthesize(
        self, text: str, voice: str, sounds_dir: Path
    ) -> Optional[Path]: ...


@dataclass(frozen=True)
class HttpTTSProvider:
    name: str
    url: str
    payload_factory: Callable[[str], dict]

    async def synthesize(
        self, text: str, voice: str, sounds_dir: Path
    ) -> Optional[Path]:
        del voice  # voice is baked into the payload
        wav_path = sounds_dir / f"{os.urandom(8).hex()}.wav"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.url,
                    json=self.payload_factory(text),
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error("%s HTTP %s: %s", self.name, resp.status, body[:200])
                        return None
                    wav_path.write_bytes(await resp.read())
                    return wav_path
        except Exception as exc:
            logger.error("%s TTS error: %s", self.name, exc)
            return None


@dataclass(frozen=True)
class EdgeTTSProvider:
    name: str = "edge"

    async def synthesize(
        self, text: str, voice: str, sounds_dir: Path
    ) -> Optional[Path]:
        mp3_path = sounds_dir / f"{os.urandom(8).hex()}.mp3"
        try:
            proc = await asyncio.create_subprocess_exec(
                "edge-tts",
                "--voice", voice,
                "--text", text,
                "--write-media", str(mp3_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error("edge-tts failed: %s", stderr.decode())
                return None
            return mp3_path
        except Exception as exc:
            logger.error("edge-tts error: %s", exc)
            return None


def _piper_payload(text: str, voice: str) -> dict:
    return {"text": text, "voice": voice}


def build_tts_registry(
    *,
    piper_url: str,
    piper_voice: str,
) -> Dict[str, TTSProvider]:
    return {
        "piper": HttpTTSProvider(
            name="piper",
            url=f"{piper_url}/synthesize",
            payload_factory=lambda text: _piper_payload(text, piper_voice),
        ),
        "edge": EdgeTTSProvider(),
    }
