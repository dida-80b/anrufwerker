"""
Database access — queue DB (jobs) and dashboard DB (calls/leads/settings).
"""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

QUEUE_DSN = os.getenv("QUEUE_DSN", "/app/data/queue.db")
DASHBOARD_DSN = os.getenv("DASHBOARD_DSN", "/app/data/dashboard.db")
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Default extraction prompt (placeholder: {transcript})
EXTRACTION_PROMPT_DEFAULT = """You are analyzing a phone call transcript for a small business and extracting structured data.

TRANSCRIPT:
{transcript}

Extract the following fields from the conversation. Reply with valid JSON only, with no text before or after it.

{
  "caller_name": "Full name or null",
  "caller_phone_raw": "Phone number as spoken or null",
  "address_street": "Street and house number or null",
  "address_plz": "Postal code (5 digits) or null",
  "address_city": "City or null",
  "description": "Short description of the request in 1-2 sentences or null",
  "urgency": "normal | urgent | emergency",
  "callback_needed": true,
  "escalated": false,
  "confidence": 0.0,
  "missing_fields": [],
  "notes": "Important observations a staff member should know, or null"
}

RULES:
- Set urgency to "emergency" only for real emergencies such as burst pipes or storm damage
- Set urgency to "urgent" when the caller explicitly stresses urgency
- confidence must be 0.0-1.0 and reflect your overall extraction confidence
- missing_fields must list the fields that could not be determined
- escalated must be true when the bot escalated the call, for example due to complaints, pricing, or legal questions
- Do NOT invent values. Use null instead of guessing"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def get_setting(key: str, default: str = "") -> str:
    """Read a setting value from the dashboard DB. Returns default on error or empty value."""
    try:
        Path(DASHBOARD_DSN).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DASHBOARD_DSN)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        conn.close()
        return row["value"] if row and row["value"] else default
    except Exception:
        return default


def get_setting_float(key: str, default: float) -> float:
    try:
        return float(get_setting(key, str(default)))
    except (ValueError, TypeError):
        return default


def get_setting_int(key: str, default: int) -> int:
    try:
        return int(get_setting(key, str(default)))
    except (ValueError, TypeError):
        return default


def queue_db() -> sqlite3.Connection:
    Path(QUEUE_DSN).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(QUEUE_DSN)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            call_id    TEXT UNIQUE NOT NULL,
            payload    TEXT NOT NULL,
            status     TEXT NOT NULL DEFAULT 'queued',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def dashboard_db() -> sqlite3.Connection:
    Path(DASHBOARD_DSN).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DASHBOARD_DSN)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if SCHEMA_PATH.exists():
        conn.executescript(SCHEMA_PATH.read_text())
    # Extraction prompt too long for the SQL INSERT OR IGNORE in schema — seed separately here
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value, description) VALUES (?, ?, ?)",
        ("extraction_prompt", EXTRACTION_PROMPT_DEFAULT,
         "Extraction prompt ({transcript} is replaced with the conversation text)"),
    )
    conn.commit()
    return conn
