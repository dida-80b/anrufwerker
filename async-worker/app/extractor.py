"""
Lead-Extraktion via Ollama.
Analysiert einen Gesprächs-Transcript und extrahiert strukturierte Felder.
"""

import json
import logging
import re

import requests

from .db import (
    EXTRACTION_PROMPT_DEFAULT,
    get_setting,
    get_setting_float,
)

logger = logging.getLogger("extractor")

_REQUIRED_FIELDS = {
    "caller_name", "caller_phone_raw", "description",
    "urgency", "callback_needed", "escalated", "confidence", "missing_fields",
}


def _transcript_to_text(messages: list) -> str:
    lines = []
    for m in messages:
        role = "Assistent" if m.get("role") == "assistant" else "Anrufer"
        lines.append(f"{role}: {m.get('content', '')}")
    return "\n".join(lines)


def _normalize_phone(raw: str | None) -> str | None:
    """Einfache E.164-Normalisierung für deutsche Nummern."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    elif digits.startswith("0"):
        digits = "+49" + digits[1:]
    elif len(digits) == 10 and not digits.startswith("+"):
        digits = "+49" + digits
    return "+" + digits.lstrip("+") if not digits.startswith("+") else digits


def extract(transcript_data: dict) -> dict:
    """
    Extrahiert strukturierte Lead-Felder aus einem Transcript.
    Gibt dict mit extrahierten Feldern zurück.
    Bei Fehler: extraction_status='failed', alle Felder None.
    """
    messages = transcript_data.get("messages", [])
    if not messages:
        return {"extraction_status": "failed", "extraction_error": "empty transcript"}

    transcript_text = _transcript_to_text(messages)

    ollama_url = get_setting("ollama_url", "http://127.0.0.1:11434/api/chat")
    ollama_model = get_setting("ollama_model", "mistral-small3.1:latest")
    confidence_threshold = get_setting_float("confidence_threshold", 0.6)
    prompt_template = get_setting("extraction_prompt", EXTRACTION_PROMPT_DEFAULT)
    prompt = prompt_template.replace("{transcript}", transcript_text)

    try:
        resp = requests.post(
            ollama_url,
            json={
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "think": False,
                "options": {"temperature": 0.1, "num_predict": 512},
            },
            timeout=60,
        )
        resp.raise_for_status()
        raw_content = resp.json()["message"]["content"].strip()

        # JSON aus Antwort extrahieren (auch wenn Modell Kommentar davor schreibt)
        match = re.search(r"\{.*\}", raw_content, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON in response: {raw_content[:200]}")

        data = json.loads(match.group())

        # Schema-Validierung: fehlende Felder loggen
        missing = _REQUIRED_FIELDS - data.keys()
        if missing:
            logger.warning(f"Ollama response missing expected fields: {missing}")

        # Phone normalisieren
        raw_phone = data.get("caller_phone_raw")
        caller_id = transcript_data.get("caller_id", "")
        if not raw_phone and caller_id:
            raw_phone = caller_id

        return {
            "extraction_status": "done",
            "extraction_confidence": float(data.get("confidence", 0.5)),
            "needs_manual_review": 1 if float(data.get("confidence", 1.0)) < confidence_threshold else 0,
            "missing_fields": json.dumps(data.get("missing_fields", []), ensure_ascii=False),
            "caller_name": data.get("caller_name"),
            "caller_phone_raw": raw_phone,
            "caller_phone_e164": _normalize_phone(raw_phone),
            "address_street": data.get("address_street"),
            "address_plz": data.get("address_plz"),
            "address_city": data.get("address_city"),
            "description": data.get("description"),
            "urgency": data.get("urgency", "normal"),
            "callback_needed": 1 if data.get("callback_needed", True) else 0,
            "escalated": 1 if data.get("escalated", False) else 0,
            "notes": data.get("notes"),
        }

    except Exception as exc:
        logger.error(f"Extraction failed: {exc}")
        return {
            "extraction_status": "failed",
            "extraction_error": str(exc)[:500],
        }
