#!/usr/bin/env python3
"""
LLM-Client — Ollama (direkt) + System-Prompt-Builder.
"""

import json
import logging
import re
from typing import AsyncGenerator

import aiohttp

from config import PROMPT_MD, PROMPT_INBOUND_MD
from settings import get_setting, get_setting_float, get_setting_int

logger = logging.getLogger("llm")

# Satzgrenzen: bei diesen Zeichen direkt TTS triggern
_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')


def build_system_prompt(company_config: dict, caller_id: str = "") -> dict:
    """
    Baut den vollständigen System-Prompt für inbound Anrufe aus der Company-Config.
    Gibt {"prompt": str, "company": str, "greeting": str} zurück.
    """
    name = company_config.get("company_name", "dem Betrieb")
    owner = company_config.get("owner_name", "dem Inhaber")
    greeting = company_config.get("greeting", f"Guten Tag, Sie haben {name} erreicht. Was kann ich für Sie tun?")
    escalation = company_config.get("escalation_message", f"{owner} ruft Sie zurück.")
    opening = company_config.get("opening_hours", "")
    services = company_config.get("services", [])
    bot_can = company_config.get("bot_can", [])
    bot_cannot = company_config.get("bot_cannot", [])
    emergency = company_config.get("emergency_number")
    phone_callback = company_config.get("phone_callback", "")
    company_since = company_config.get("company_since", "")
    company_address = company_config.get("company_address", "")
    employee_count = company_config.get("employee_count", "")

    bot_can_labels = {
        "anfrage_aufnehmen": (
            "Anfrage aufnehmen in dieser Reihenfolge: "
            "1. Vollständigen Namen erfragen. "
            "2. Adresse/Ort erfragen und Postleitzahl bestätigen (z.B. 'Musterstadt, Postleitzahl 80000?'). "
            "3. Kurzes Anliegen aufnehmen (was soll gemacht werden). "
            "4. Rückruf ankündigen: falls ANRUFER-NUMMER bekannt: "
            f"'Darf ich Sie später unter dieser Nummer zurückrufen um Termine zur Baubegehung abzuklären?' — "
            "bei Ablehnung korrekte Nummer aufnehmen und bestätigen. "
            f"5. Abschließen: 'Ich gebe das an {owner} weiter und wir melden uns.' "
            "KEIN Wunschtermin erfragen — Termine werden beim Rückruf abgeklärt."
        ),
        "infos_geben": (
            "Informationen zu Betrieb, Leistungen und Öffnungszeiten geben. "
            "Halte dich an die konfigurierten Angaben. Erfinde nichts."
        ),
        "oeffnungszeiten": "Öffnungszeiten nennen.",
    }
    bot_cannot_labels = {
        "preise_verhandeln": "Preise nennen oder verhandeln",
        "beschwerden": "Beschwerden entgegennehmen",
        "rechtliches": "Rechtliche Fragen beantworten",
    }

    bot_can_custom = company_config.get("bot_can_custom", {})
    bot_can_labels.update(bot_can_custom)

    can_lines = "\n".join(
        f"- {bot_can_labels.get(c, c)}" for c in bot_can
    ) if bot_can else "- Allgemeine Auskünfte geben"
    cannot_lines = "\n".join(
        f"- {bot_cannot_labels.get(c, c)}" for c in bot_cannot
    ) if bot_cannot else ""

    services_str = ", ".join(services) if services else ""

    # Systemprompt: DB hat Vorrang, Datei ist Fallback
    base_rules = get_setting("system_prompt_inbound")
    if not base_rules and PROMPT_INBOUND_MD.exists():
        base_rules = PROMPT_INBOUND_MD.read_text(encoding="utf-8").strip()

    prompt = f"""Du bist der KI-Telefonassistent von {name}.
Du nimmst Anrufe entgegen für {owner}.

BEGRÜSSUNG:
Wenn du "[GESPRÄCH BEGINNT]" erhältst, sage genau: "{greeting}"
Danach NICHT erneut begrüßen, außer der Anruf wurde neu gestartet.

DU KANNST:
{can_lines}

DU KANNST NICHT — ESKALIERE:
{cannot_lines}
→ Sage dann: "{escalation}"

KRITISCHE REGELN:
- PHONE_CALLBACK_BETRIEB ist die feste Betriebsnummer, NICHT die Kundennummer — niemals als Kundennummer ausgeben.
- ANRUFER-NUMMER ist die Nummer des Anrufers — für Rückruf-Bestätigung nutzen.
- Kein Wunschtermin erfragen — Termine werden beim Rückruf abgeklärt.
- Nenne niemals erfundene oder unbestätigte Nummern.
"""

    if emergency:
        prompt += f"\nNOTFALL: {emergency}\n"
    if opening:
        prompt += f"\nÖFFNUNGSZEITEN: {opening}\n"
    if services_str:
        prompt += f"\nDIENSTLEISTUNGEN: {services_str}\n"
    if company_since:
        prompt += f"\nGEGRÜNDET: {company_since}\n"
    if company_address:
        prompt += f"\nANSCHRIFT BETRIEB: {company_address}\n"
    if employee_count:
        prompt += f"\nMITARBEITER: {employee_count}\n"
    if caller_id:
        prompt += f"\nANRUFER-NUMMER: {caller_id}\n"
    if phone_callback:
        prompt += f"\nPHONE_CALLBACK_BETRIEB: {phone_callback}\n"
    if base_rules:
        prompt += f"\n---\n{base_rules}"

    return {"prompt": prompt, "company": name, "greeting": greeting}


async def stream_response(
    session_uuid: str,
    messages: list,
    mission: str = "",
    system_prompt: str = "",
) -> AsyncGenerator[str, None]:
    """
    Async generator: streamt Ollama-Antwort, liefert vollständige Sätze.

    Args:
        session_uuid:  UUID des laufenden Anrufs (für Logging)
        messages:      Vollständige Gesprächshistorie inkl. aktuellem User-Turn
        mission:       Optionale Aufgabe (outbound calls)
        system_prompt: Optionaler Override (inbound: aus company config)
    """
    if not messages:
        return

    # LLM-Params per Call aus DB lesen (kein Restart nötig bei Änderungen)
    ollama_url   = get_setting("llm_url",           "OLLAMA_URL",   "http://host.docker.internal:11434/api/chat")
    ollama_model = get_setting("llm_model",         "OLLAMA_MODEL", "qwen3.5-tel:latest")
    temperature  = get_setting_float("llm_temperature",  "OLLAMA_TEMPERATURE",  0.1)
    top_p        = get_setting_float("llm_top_p",        "OLLAMA_TOP_P",        0.85)
    num_predict  = get_setting_int("llm_num_predict",    "OLLAMA_NUM_PREDICT",  80)
    repeat_pen   = get_setting_float("llm_repeat_penalty","OLLAMA_REPEAT_PENALTY",1.2)
    num_ctx      = get_setting_int("llm_num_ctx",        "OLLAMA_NUM_CTX",      2048)

    if system_prompt:
        system_content = system_prompt
    else:
        # prompt.md live lesen damit Änderungen sofort wirken (kein Neustart nötig)
        system_content = (
            PROMPT_MD.read_text(encoding="utf-8").strip()
            if PROMPT_MD.exists()
            else ""
        )
        if mission:
            system_content += (
                f"\n\nDeine Aufgabe für diesen Anruf: {mission}"
                f"\nWenn du '[GESPRÄCH BEGINNT]' erhältst, starte sofort mit einer kurzen Begrüßung"
                f" und erfülle deine Aufgabe. Maximal 1-2 Sätze."
            )

    payload = {
        "model": ollama_model,
        "messages": [{"role": "system", "content": system_content}] + messages,
        "stream": True,
        "think": False,
        "options": {
            "temperature": temperature,
            "top_p": top_p,
            "num_predict": num_predict,
            "repeat_penalty": repeat_pen,
            "num_ctx": num_ctx,
        }
    }

    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    logger.info(f"[{session_uuid}] Ollama → {ollama_model}: {last_user[:60]}")

    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                ollama_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=None, connect=5, sock_read=60),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"[{session_uuid}] Ollama {resp.status}: {body[:200]}")
                    yield "Entschuldigung, da ist etwas schiefgelaufen."
                    return

                buffer = ""
                while True:
                    raw_line = await resp.content.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue

                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        logger.debug(f"[{session_uuid}] JSON parse error: {line[:80]}")
                        continue

                    msg = chunk.get("message", {})
                    if not isinstance(msg, dict):
                        continue
                    token = msg.get("content", "")
                    if not token:
                        continue

                    buffer += token

                    # <think>...</think> vollständig entfernen (Reasoning-Modelle)
                    buffer = re.sub(r'<think>.*?</think>', '', buffer, flags=re.DOTALL)
                    if '<think>' in buffer:
                        continue

                    parts = _SENTENCE_END.split(buffer)
                    for sentence in parts[:-1]:
                        sentence = sentence.strip()
                        if sentence:
                            yield sentence
                    buffer = parts[-1]

                # Restlichen Buffer ausgeben — offenen <think>-Block abschneiden
                if '<think>' in buffer:
                    buffer = buffer[:buffer.index('<think>')]
                if buffer.strip():
                    yield buffer.strip()

    except Exception as exc:
        logger.error(f"[{session_uuid}] Ollama stream error: {exc}")
        yield "Entschuldigung, kein Ollama erreichbar."
