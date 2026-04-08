"""
Job processor: dequeues jobs, writes calls + leads into the dashboard DB.
"""

import json
import logging

from .db import _now, dashboard_db, get_setting, get_setting_int, queue_db
from .extractor import extract

logger = logging.getLogger("processor")


def _get_or_create_tenant(conn, company_name: str) -> str:
    """Return tenant_id — creates the tenant if it does not exist."""
    slug = company_name.lower().replace(" ", "-").replace("&", "und")[:64]
    row = conn.execute("SELECT id FROM tenants WHERE slug=?", (slug,)).fetchone()
    if row:
        return row["id"]
    tid = conn.execute(
        "INSERT INTO tenants (slug, name) VALUES (?, ?) RETURNING id",
        (slug, company_name),
    ).fetchone()["id"]
    logger.info(f"Tenant created: {company_name} ({tid})")
    return tid


def _upsert_call(conn, tenant_id: str, transcript: dict) -> str:
    """Write raw call data to DB. Returns call_id."""
    session_uuid = transcript["session_uuid"]
    existing = conn.execute(
        "SELECT id FROM calls WHERE session_uuid=?", (session_uuid,)
    ).fetchone()
    if existing:
        return existing["id"]

    # caller_id from transcript → caller_number in DB field
    caller_number = transcript.get("caller_id") or None
    started_at = transcript.get("timestamp", _now())
    messages = transcript.get("messages", [])
    turn_count = len([m for m in messages if m.get("role") == "user"])

    duration_factor = get_setting_int("duration_factor", 15)
    duration_est = turn_count * duration_factor
    stt_provider = get_setting("stt_provider", "whisper-large-v3-turbo")

    call_id = conn.execute(
        """
        INSERT INTO calls (
            tenant_id, session_uuid, direction,
            caller_number, started_at, ended_at, duration_seconds,
            turn_count, transcript, transcript_status,
            stt_provider, extraction_status, call_status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        RETURNING id
        """,
        (
            tenant_id,
            session_uuid,
            transcript.get("direction", "inbound"),
            caller_number,
            started_at,
            started_at,
            duration_est,
            turn_count,
            json.dumps(transcript.get("messages", []), ensure_ascii=False),
            "done",
            stt_provider,
            "pending",
            "completed",
        ),
    ).fetchone()["id"]

    logger.info(f"Call saved: {session_uuid} → {call_id}")
    return call_id


def _upsert_lead(conn, tenant_id: str, call_id: str, extracted: dict) -> str:
    """Create lead from extracted data. Returns lead_id."""
    existing = conn.execute(
        "SELECT lead_id FROM lead_calls WHERE call_id=?", (call_id,)
    ).fetchone()
    if existing:
        return existing["lead_id"]

    status = extracted.get("extraction_status", "failed")
    now = _now()

    lead_id = conn.execute(
        """
        INSERT INTO leads (
            tenant_id, extraction_status, extraction_confidence,
            needs_manual_review, missing_fields,
            caller_name, caller_phone_raw, caller_phone_e164,
            address_street, address_plz, address_city,
            description, urgency, callback_needed, escalated,
            notes, status, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        RETURNING id
        """,
        (
            tenant_id,
            status,
            extracted.get("extraction_confidence"),
            extracted.get("needs_manual_review", 0),
            extracted.get("missing_fields"),
            extracted.get("caller_name"),
            extracted.get("caller_phone_raw"),
            extracted.get("caller_phone_e164"),
            extracted.get("address_street"),
            extracted.get("address_plz"),
            extracted.get("address_city"),
            extracted.get("description"),
            extracted.get("urgency", "normal"),
            extracted.get("callback_needed", 1),
            extracted.get("escalated", 0),
            extracted.get("notes"),
            "needs_review" if extracted.get("needs_manual_review") else "new",
            now,
            now,
        ),
    ).fetchone()["id"]

    conn.execute(
        "INSERT INTO lead_calls (lead_id, call_id, is_origin) VALUES (?,?,1)",
        (lead_id, call_id),
    )

    conn.execute(
        """
        INSERT INTO lead_events (lead_id, actor_type, actor_id, event_type, new_value, payload)
        VALUES (?, 'worker', 'async-worker', 'extraction_done', ?, ?)
        """,
        (
            lead_id,
            status,
            json.dumps({
                "confidence": extracted.get("extraction_confidence"),
                "missing_fields": extracted.get("missing_fields"),
                "error": extracted.get("extraction_error"),
            }, ensure_ascii=False),
        ),
    )

    logger.info(f"Lead saved: {lead_id} (status={status})")
    return lead_id


def _update_call_extraction(conn, call_id: str, status: str, error: str | None):
    conn.execute(
        "UPDATE calls SET extraction_status=? WHERE id=?",
        (status, call_id),
    )
    if error:
        conn.execute(
            "UPDATE calls SET extraction_error=? WHERE id=?",
            (error, call_id),
        )


def process_job(job_id: int, call_uuid: str, payload_raw: str) -> bool:
    """
    Process a job:
    1. Transcript → calls table
    2. Ollama extraction → leads table
    3. Mark job as 'done'
    Returns True on success.
    """
    try:
        transcript = json.loads(payload_raw)
        company = transcript.get("company", "Unknown Business")

        dash = dashboard_db()
        try:
            with dash:
                tenant_id = _get_or_create_tenant(dash, company)
                call_id = _upsert_call(dash, tenant_id, transcript)
                dash.execute(
                    "UPDATE calls SET extraction_status='running' WHERE id=?", (call_id,)
                )

            logger.info(f"Starting extraction for {call_uuid}")
            extracted = extract(transcript)

            with dash:
                _update_call_extraction(
                    dash, call_id,
                    extracted.get("extraction_status", "failed"),
                    extracted.get("extraction_error"),
                )
                _upsert_lead(dash, tenant_id, call_id, extracted)
        finally:
            dash.close()

        q = queue_db()
        try:
            with q:
                q.execute(
                    "UPDATE jobs SET status='done', updated_at=? WHERE id=?",
                    (_now(), job_id),
                )
        finally:
            q.close()

        logger.info(f"Job {job_id} ({call_uuid}) processed successfully")
        return True

    except Exception as exc:
        logger.error(f"Job {job_id} ({call_uuid}) failed: {exc}")
        try:
            q = queue_db()
            try:
                with q:
                    q.execute(
                        "UPDATE jobs SET status='failed', updated_at=? WHERE id=?",
                        (_now(), job_id),
                    )
            finally:
                q.close()
        except Exception:
            pass
        return False
