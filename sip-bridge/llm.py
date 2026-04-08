#!/usr/bin/env python3
"""
LLM client — Ollama (direct) + system prompt builder.
"""

import json
import logging
import re
from typing import AsyncGenerator

import aiohttp

from config import PROMPT_MD, PROMPT_INBOUND_MD
from settings import get_setting, get_setting_float, get_setting_int

logger = logging.getLogger("llm")

# Sentence boundaries: trigger TTS immediately at these characters
_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')


def build_system_prompt(company_config: dict, caller_id: str = "") -> dict:
    """
    Build the full system prompt for inbound calls from the company config.
    Returns {"prompt": str, "company": str, "greeting": str}.
    """
    name = company_config.get("company_name", "the business")
    owner = company_config.get("owner_name", "the owner")
    greeting = company_config.get("greeting", f"Hello, you have reached {name}. How can I help you?")
    escalation = company_config.get("escalation_message", f"{owner} will call you back.")
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
            "Capture the request in this order: "
            "1. Ask for the full name. "
            "2. Ask for the address or city and confirm the postal code, for example 'Sampletown, postal code 80000?'. "
            "3. Capture a short description of the request. "
            "4. Confirm the callback. If CALLER_NUMBER is available, say: "
            f"'May we call you back later at this number to discuss next steps?' "
            "If the caller refuses, collect and confirm the correct number. "
            f"5. Close with: 'I will pass this on to {owner} and we will get back to you.' "
            "Do NOT ask for a preferred appointment time. Scheduling is handled during the callback."
        ),
        "infos_geben": (
            "Provide information about the business, services, and opening hours. "
            "Stick to the configured details. Do not invent anything."
        ),
        "oeffnungszeiten": "Share the opening hours.",
    }
    bot_cannot_labels = {
        "preise_verhandeln": "Quote or negotiate prices",
        "beschwerden": "Handle complaints",
        "rechtliches": "Answer legal questions",
    }

    bot_can_custom = company_config.get("bot_can_custom", {})
    bot_can_labels.update(bot_can_custom)

    can_lines = "\n".join(
        f"- {bot_can_labels.get(c, c)}" for c in bot_can
    ) if bot_can else "- Provide general information"
    cannot_lines = "\n".join(
        f"- {bot_cannot_labels.get(c, c)}" for c in bot_cannot
    ) if bot_cannot else ""

    services_str = ", ".join(services) if services else ""

    # System prompt: DB takes priority, file is fallback
    base_rules = get_setting("system_prompt_inbound")
    if not base_rules and PROMPT_INBOUND_MD.exists():
        base_rules = PROMPT_INBOUND_MD.read_text(encoding="utf-8").strip()

    prompt = f"""You are the AI phone assistant for {name}.
You are answering calls on behalf of {owner}.

GREETING:
When you receive "[CALL STARTS]", say exactly: "{greeting}"
Do NOT greet again unless the call was restarted.

YOU MAY:
{can_lines}

YOU MAY NOT — ESCALATE:
{cannot_lines}
Then say: "{escalation}"

CRITICAL RULES:
- PHONE_CALLBACK_BETRIEB is the company's fixed phone number, NOT the customer's number. Never present it as the customer's number.
- ANRUFER-NUMMER is the caller's number and should be used for callback confirmation.
- Do not ask for a preferred appointment slot. Scheduling happens later during the callback.
- Never mention invented or unconfirmed numbers.
"""

    if emergency:
        prompt += f"\nEMERGENCY: {emergency}\n"
    if opening:
        prompt += f"\nOPENING HOURS: {opening}\n"
    if services_str:
        prompt += f"\nSERVICES: {services_str}\n"
    if company_since:
        prompt += f"\nFOUNDED: {company_since}\n"
    if company_address:
        prompt += f"\nBUSINESS ADDRESS: {company_address}\n"
    if employee_count:
        prompt += f"\nEMPLOYEES: {employee_count}\n"
    if caller_id:
        prompt += f"\nCALLER_NUMBER: {caller_id}\n"
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
    Async generator: streams Ollama response, yields complete sentences.

    Args:
        session_uuid:  UUID of the active call (for logging)
        messages:      Full conversation history including current user turn
        mission:       Optional task (outbound calls)
        system_prompt: Optional override (inbound: from company config)
    """
    if not messages:
        return

    # Read LLM params from DB per call (no restart needed when settings change)
    ollama_url   = get_setting("llm_url",           "OLLAMA_URL",   "http://host.docker.internal:11434/api/chat")
    ollama_model = get_setting("llm_model",         "OLLAMA_MODEL", "ministral-3:14b-instruct-2512-q8_0")
    temperature  = get_setting_float("llm_temperature",  "OLLAMA_TEMPERATURE",  0.1)
    top_p        = get_setting_float("llm_top_p",        "OLLAMA_TOP_P",        0.85)
    num_predict  = get_setting_int("llm_num_predict",    "OLLAMA_NUM_PREDICT",  80)
    repeat_pen   = get_setting_float("llm_repeat_penalty","OLLAMA_REPEAT_PENALTY",1.2)
    num_ctx      = get_setting_int("llm_num_ctx",        "OLLAMA_NUM_CTX",      2048)

    if system_prompt:
        system_content = system_prompt
    else:
        # Read prompt.md live so changes take effect immediately (no restart needed)
        system_content = (
            PROMPT_MD.read_text(encoding="utf-8").strip()
            if PROMPT_MD.exists()
            else ""
        )
        if mission:
            system_content += (
                f"\n\nYour task for this call: {mission}"
                f"\nWhen you receive '[CALL STARTS]', begin immediately with a short greeting"
                f" and complete your task. Use at most 1-2 sentences."
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
                    yield "Sorry, something went wrong."
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

                    # Strip <think>...</think> completely (reasoning models)
                    buffer = re.sub(r'<think>.*?</think>', '', buffer, flags=re.DOTALL)
                    if '<think>' in buffer:
                        continue

                    parts = _SENTENCE_END.split(buffer)
                    for sentence in parts[:-1]:
                        sentence = sentence.strip()
                        if sentence:
                            yield sentence
                    buffer = parts[-1]

                # Flush remaining buffer — truncate any open <think> block
                if '<think>' in buffer:
                    buffer = buffer[:buffer.index('<think>')]
                if buffer.strip():
                    yield buffer.strip()

    except Exception as exc:
        logger.error(f"[{session_uuid}] Ollama stream error: {exc}")
        yield "Sorry, Ollama is not reachable."
