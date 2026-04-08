"""
Settings-Zugriff für den sip-bridge.
Liest aus der shared dashboard.db — DB hat Vorrang, Env-Var ist Fallback.
"""

import os
import sqlite3
from pathlib import Path

DASHBOARD_DSN = os.getenv("DASHBOARD_DSN", "/app/data/dashboard.db")

SETTINGS_DEFAULTS = {
    "llm_url": ("OLLAMA_URL", "http://host.docker.internal:11434/api/chat", "Ollama URL (Telefon-KI)"),
    "llm_model": ("OLLAMA_MODEL", "ministral-3:14b-instruct-2512-q8_0", "Ollama Modell für Telefonie"),
    "llm_temperature": ("OLLAMA_TEMPERATURE", "0.1", "Temperature (0.0–1.0)"),
    "llm_top_p": ("OLLAMA_TOP_P", "0.85", "Top-P (0.0–1.0)"),
    "llm_num_predict": ("OLLAMA_NUM_PREDICT", "80", "Max. Tokens pro Antwort"),
    "llm_repeat_penalty": ("OLLAMA_REPEAT_PENALTY", "1.2", "Repeat Penalty"),
    "llm_num_ctx": ("OLLAMA_NUM_CTX", "2048", "Kontext-Größe"),
    "tts_engine": ("TTS_ENGINE", "piper", "TTS-Engine für Telefonie"),
    "tts_voice": ("TTS_VOICE", "de-DE-SeraphinaMultilingualNeural", "Edge-TTS Stimme"),
    "piper_url": ("PIPER_URL", "http://127.0.0.1:5150", "Piper HTTP URL"),
    "piper_voice": ("PIPER_VOICE", "de_DE-thorsten-high", "Piper Voice"),
    "stt_engine": ("STT_ENGINE", "whisper-http", "STT-Engine"),
    "whisper_url": ("WHISPER_URL", "http://127.0.0.1:8090", "Whisper HTTP URL"),
    "vad_speech_frames_to_start": ("VAD_SPEECH_FRAMES_TO_START", "2", "Frames bis Sprachstart"),
    "vad_silence_frames_to_end": ("VAD_SILENCE_FRAMES_TO_END", "12", "Stille-Frames bis Turn-Ende"),
    "vad_rms_threshold": ("VAD_RMS_THRESHOLD", "260", "RMS-Schwelle Sprache"),
    "vad_barge_in_threshold": ("VAD_BARGE_IN_THRESHOLD", "2000", "RMS-Schwelle Barge-In"),
    "vad_barge_in_frames": ("VAD_BARGE_IN_FRAMES", "50", "Frames bis Barge-In"),
    "preroll_frames": ("PREROLL_FRAMES", "8", "Preroll-Frames"),
    "min_user_rms_process": ("MIN_USER_RMS_PROCESS", "150", "Mindestrms für STT-Verarbeitung"),
    "inactivity_timeout": ("INACTIVITY_TIMEOUT", "90", "Timeout bis Auflegen"),
    "checkin_timeout": ("CHECKIN_TIMEOUT", "10", "Timeout bis Check-In"),
    "max_tts_seconds_per_sentence": ("MAX_TTS_SECONDS_PER_SENTENCE", "10.0", "Max. TTS-Sekunden pro Satz"),
    "max_tts_sentences_per_turn": ("MAX_TTS_SENTENCES_PER_TURN", "2", "Max. TTS-Sätze pro Turn"),
    "max_tts_seconds_intro": ("MAX_TTS_SECONDS_INTRO", "8.0", "Max. Intro-Länge"),
    "no_regreet_after_intro": ("NO_REGREET_AFTER_INTRO", "true", "Keine erneute Begrüßung"),
    "process_buffered_during_llm": ("PROCESS_BUFFERED_DURING_LLM", "false", "Audio während LLM weiterverarbeiten"),
}


def get_setting(key: str, env_var: str = None, default: str = "") -> str:
    """Liest Setting aus DB. Fällt auf env_var zurück, dann auf default."""
    try:
        conn = sqlite3.connect(DASHBOARD_DSN)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        conn.close()
        if row and row["value"]:
            return row["value"]
    except Exception:
        pass
    if env_var:
        val = os.getenv(env_var)
        if val:
            return val
    return default


def get_setting_float(key: str, env_var: str = None, default: float = 0.0) -> float:
    try:
        return float(get_setting(key, env_var, str(default)))
    except (ValueError, TypeError):
        return default


def get_setting_int(key: str, env_var: str = None, default: int = 0) -> int:
    try:
        return int(get_setting(key, env_var, str(default)))
    except (ValueError, TypeError):
        return default


def get_setting_bool(key: str, env_var: str = None, default: bool = False) -> bool:
    val = get_setting(key, env_var, "true" if default else "false")
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


def load_company_config() -> dict:
    """Lädt Firmenkonfiguration aus DB. Fällt auf JSON-Datei zurück wenn company_name leer."""
    def _list(key: str, default: str = "") -> list:
        val = get_setting(key, default=default)
        return [s.strip() for s in val.split(",") if s.strip()]

    cfg = {
        "company_name":        get_setting("company_name"),
        "owner_name":          get_setting("company_owner"),
        "phone_callback":      get_setting("company_phone_callback"),
        "greeting":            get_setting("company_greeting"),
        "services":            _list("company_services"),
        "opening_hours":       get_setting("company_opening_hours"),
        "escalation_message":  get_setting("company_escalation_message"),
        "company_address":     get_setting("company_address"),
        "company_since":       get_setting("company_since"),
        "employee_count":      get_setting("company_employee_count"),
        "emergency_number":    get_setting("company_emergency_number") or None,
        "bot_can":             _list("company_bot_can", "anfrage_aufnehmen,infos_geben,oeffnungszeiten"),
        "bot_cannot":          _list("company_bot_cannot", "preise_verhandeln,beschwerden,rechtliches"),
    }

    # Fallback auf JSON-Datei wenn DB noch nicht befüllt
    if not cfg["company_name"]:
        import json
        cfg_path = os.getenv("COMPANY_CONFIG", "")
        if cfg_path:
            p = Path(cfg_path)
            if p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    pass

    return cfg


def seed_from_config(company_config: dict):
    """Schreibt Werte aus company_config JSON in DB — nur wenn DB-Wert noch leer ist."""
    if not company_config:
        return

    services = company_config.get("services", [])
    mappings = {
        "company_name":              company_config.get("company_name", ""),
        "company_owner":             company_config.get("owner_name", ""),
        "company_phone_callback":    company_config.get("phone_callback", ""),
        "company_greeting":          company_config.get("greeting", ""),
        "company_services":          ", ".join(services) if services else "",
        "company_opening_hours":     company_config.get("opening_hours", ""),
        "company_escalation_message":company_config.get("escalation_message", ""),
        "company_address":           company_config.get("company_address", ""),
        "company_since":             company_config.get("company_since", ""),
        "company_employee_count":    company_config.get("employee_count", ""),
        "company_emergency_number":  company_config.get("emergency_number", "") or "",
        "company_bot_can":           ",".join(company_config.get("bot_can", [])),
        "company_bot_cannot":        ",".join(company_config.get("bot_cannot", [])),
    }

    try:
        conn = sqlite3.connect(DASHBOARD_DSN)
        for key, value in mappings.items():
            if value:
                conn.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )
        conn.commit()
        conn.close()
    except Exception:
        pass


def seed_runtime_settings():
    """Schreibt Runtime-Defaults aus Env/Defaults in DB, sofern der Key noch fehlt."""
    try:
        conn = sqlite3.connect(DASHBOARD_DSN)
        for key, (env_var, default, description) in SETTINGS_DEFAULTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value, description) VALUES (?, ?, ?)",
                (key, os.getenv(env_var, default), description),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass


def seed_system_prompt(prompt_path: Path):
    """Schreibt Inhalt von prompt_inbound.md in DB — nur wenn DB-Wert noch leer ist."""
    if not prompt_path.exists():
        return
    try:
        content = prompt_path.read_text(encoding="utf-8").strip()
        conn = sqlite3.connect(DASHBOARD_DSN)
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value, description) VALUES (?, ?, ?)",
            ("system_prompt_inbound", content, "Inbound-Systemprompt (Telefon-Regeln)"),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
