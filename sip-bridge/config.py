#!/usr/bin/env python3
"""
Central configuration — all env vars in one place.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("config")

# ============================================================
# Asterisk / ARI
# ============================================================

ASTERISK_HOST = os.getenv("ASTERISK_HOST", "127.0.0.1")
ASTERISK_ARI_PORT = int(os.getenv("ASTERISK_ARI_PORT", "8088"))
ASTERISK_ARI_USER = os.getenv("ASTERISK_ARI_USER", "")
ASTERISK_ARI_PASS = os.getenv("ASTERISK_ARI_PASSWORD", "")

# ============================================================
# Logging
# ============================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ============================================================
# Bridge / HTTP
# ============================================================

BRIDGE_PORT = int(os.getenv("BRIDGE_PORT", "5000"))
SOUNDS_DIR = Path(os.getenv("SOUNDS_DIR", "/sounds"))
TRANSCRIPTS_PATH = Path(os.getenv("TRANSCRIPTS_PATH", "/app/data/transcripts"))
TTS_VOICE = os.getenv("TTS_VOICE", "de-DE-SeraphinaMultilingualNeural")
FRITZBOX_SIP_USER = os.getenv("FRITZBOX_SIP_USER", "")

# ============================================================
# TTS
# ============================================================

TTS_ENGINE = os.getenv("TTS_ENGINE", "piper")   # "piper" (local) | "edge" (Microsoft Azure Neural)
PIPER_VOICE = os.getenv("PIPER_VOICE", "de_DE-thorsten-high")
PIPER_URL = os.getenv("PIPER_URL", "http://127.0.0.1:5150")

# ============================================================
# AudioSocket
# ============================================================

AUDIOSOCKET_PORT = int(os.getenv("AUDIOSOCKET_PORT", "9090"))

# ============================================================
# STT
# ============================================================

STT_ENGINE = os.getenv("STT_ENGINE", "whisper-http")
WHISPER_URL = os.getenv("WHISPER_URL", "http://127.0.0.1:8090")

# ============================================================
# VAD
# ============================================================

MIN_AUDIO_CHUNK_MS = int(os.getenv("MIN_AUDIO_CHUNK_MS", "280"))
MAX_AUDIO_CHUNK_MS = int(os.getenv("MAX_AUDIO_CHUNK_MS", "1800"))
VAD_SPEECH_FRAMES_TO_START = int(os.getenv("VAD_SPEECH_FRAMES_TO_START", "2"))
VAD_SILENCE_FRAMES_TO_END = int(os.getenv("VAD_SILENCE_FRAMES_TO_END", "12"))
VAD_RMS_THRESHOLD = int(os.getenv("VAD_RMS_THRESHOLD", "260"))
VAD_BARGE_IN_THRESHOLD = int(os.getenv("VAD_BARGE_IN_THRESHOLD", "2000"))
VAD_BARGE_IN_FRAMES = int(os.getenv("VAD_BARGE_IN_FRAMES", "50"))
PREROLL_FRAMES = int(os.getenv("PREROLL_FRAMES", "8"))
MIN_USER_RMS_PROCESS = int(os.getenv("MIN_USER_RMS_PROCESS", "150"))

# ============================================================
# Session / Timeouts
# ============================================================

INACTIVITY_TIMEOUT = int(os.getenv("INACTIVITY_TIMEOUT", "90"))
CHECKIN_TIMEOUT = int(os.getenv("CHECKIN_TIMEOUT", "10"))
MAX_TTS_SECONDS_PER_SENTENCE = float(os.getenv("MAX_TTS_SECONDS_PER_SENTENCE", "10.0"))
MAX_TTS_SENTENCES_PER_TURN = int(os.getenv("MAX_TTS_SENTENCES_PER_TURN", "2"))
MAX_TTS_SECONDS_INTRO = float(os.getenv("MAX_TTS_SECONDS_INTRO", "8.0"))
NO_REGREET_AFTER_INTRO = os.getenv("NO_REGREET_AFTER_INTRO", "true").lower() == "true"
PROCESS_BUFFERED_DURING_LLM = (
    os.getenv("PROCESS_BUFFERED_DURING_LLM", "false").lower() == "true"
)

# ============================================================
# LLM / Ollama
# ============================================================

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "ministral-3:14b-instruct-2512-q8_0")
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.1"))
OLLAMA_TOP_P = float(os.getenv("OLLAMA_TOP_P", "0.85"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "24"))
OLLAMA_REPEAT_PENALTY = float(os.getenv("OLLAMA_REPEAT_PENALTY", "1.2"))
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "2048"))

PROMPT_MD = Path("/app/prompt.md")
PROMPT_INBOUND_MD = Path("/app/prompt_inbound.md")

# ============================================================
# Inbound / Company Config
# ============================================================

COMPANY_CONFIG_PATH = os.getenv("COMPANY_CONFIG", "")
INBOUND_ENABLED = os.getenv("INBOUND_ENABLED", "false").lower() == "true"

company_config: dict = {}
if COMPANY_CONFIG_PATH:
    _cfg_path = Path(COMPANY_CONFIG_PATH)
    if _cfg_path.exists():
        company_config = json.loads(_cfg_path.read_text(encoding="utf-8"))
    else:
        logger.warning(f"COMPANY_CONFIG path not found: {COMPANY_CONFIG_PATH}")

# ============================================================
# Async-Worker
# ============================================================

ASYNC_WORKER_QUEUE_DSN = os.getenv("ASYNC_WORKER_QUEUE_DSN", "/app/data/queue.db")
ASYNC_WORKER_DISABLED = os.getenv("ASYNC_WORKER_DISABLED", "false").lower() == "true"
