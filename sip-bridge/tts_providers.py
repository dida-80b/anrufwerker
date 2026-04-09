#!/usr/bin/env python3
"""
TTS provider registry.

Aktuell unterstützte Engines (tts_engine in DB/Settings):
  piper  — lokaler Piper HTTP-Dienst (ONNX), erwartet POST /synthesize {text, voice}
  edge   — edge-tts Subprocess (Microsoft Azure Neural, benötigt Internet)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEUE HTTP-KOMPATIBLE ENGINE HINZUFÜGEN (z. B. StyleTTS2, F5-TTS, Coqui, …)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Voraussetzung: Die neue Engine muss einen HTTP-Endpoint haben der
  POST /synthesize
  Body: {"text": "...", "voice": "..."}
  Antwort: rohe Audio-Bytes (WAV)
akzeptiert. Wenn der Endpoint-Pfad oder das Payload-Format abweicht:
→ Eigene Provider-Klasse analog zu EdgeTTSProvider schreiben (siehe unten).

Schritt 1 — Eintrag in build_tts_registry() hinzufügen:

    "meine-engine": HttpTTSProvider(name="meine-engine", url=f"{tts_url}/synthesize"),

  Wenn die Engine einen anderen Pfad hat (z. B. /tts oder /api/generate):

    "meine-engine": HttpTTSProvider(name="meine-engine", url=f"{tts_url}/tts"),

Schritt 2 — In den Admin-Settings setzen:
  tts_engine  →  meine-engine
  tts_url     →  http://127.0.0.1:PORT
  tts_voice   →  stimmen-name-laut-engine-doku

Kein Neustart des Containers nötig — Settings werden per Call aus der DB gelesen.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EIGENE PROVIDER-KLASSE (für nicht HTTP-kompatible Engines)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Wenn die Engine ein anderes Interface hat (anderes Payload-Format, Subprocess,
gRPC, etc.), eine neue @dataclass analog zu EdgeTTSProvider schreiben:

    @dataclass(frozen=True)
    class MyEngineTTSProvider:
        name: str = "meine-engine"

        async def synthesize(self, text: str, voice: str, sounds_dir: Path) -> Optional[Path]:
            # … Audio erzeugen, Datei in sounds_dir schreiben, Pfad zurückgeben
            # Bei Fehler: None zurückgeben (kein raise — der Anruf bleibt aktiv)
            ...

Dann in build_tts_registry() eintragen:
    "meine-engine": MyEngineTTSProvider(),
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
    """Generic HTTP TTS provider: POST {url} with {text, voice} → WAV bytes."""
    name: str
    url: str

    async def synthesize(
        self, text: str, voice: str, sounds_dir: Path
    ) -> Optional[Path]:
        wav_path = sounds_dir / f"{os.urandom(8).hex()}.wav"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.url,
                    json={"text": text, "voice": voice},
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


def build_tts_registry(*, tts_url: str) -> Dict[str, TTSProvider]:
    """
    Build the engine registry. tts_url is the HTTP endpoint for all HTTP-based engines.
    Voice is passed dynamically at synthesis time — not baked in at build time.
    """
    return {
        "piper": HttpTTSProvider(name="piper", url=f"{tts_url}/synthesize"),
        "edge": EdgeTTSProvider(),
    }
