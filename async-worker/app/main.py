import asyncio
import logging
import os

import requests
from fastapi import FastAPI

from .db import _now, dashboard_db, get_setting, queue_db
from .processor import process_job

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("async-worker")

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "10"))

app = FastAPI(title="anrufwerker-async-worker", version="0.2.0")


async def _poll_loop():
    """Pollt die Queue alle POLL_INTERVAL Sekunden und verarbeitet Jobs."""
    logger.info(f"Worker-Loop gestartet (Intervall: {POLL_INTERVAL}s)")
    while True:
        try:
            conn = queue_db()
            row = conn.execute(
                "SELECT id, call_id, payload FROM jobs WHERE status='queued' ORDER BY id LIMIT 1"
            ).fetchone()
            conn.close()

            if row:
                conn2 = queue_db()
                updated = conn2.execute(
                    "UPDATE jobs SET status='running', updated_at=? WHERE id=? AND status='queued'",
                    (_now(), row["id"]),
                ).rowcount
                conn2.commit()
                conn2.close()
                if not updated:
                    continue  # anderer Worker hat ihn schon
                logger.info(f"Job gefunden: {row['call_id']}")
                await asyncio.get_event_loop().run_in_executor(
                    None, process_job, row["id"], row["call_id"], row["payload"]
                )
            else:
                await asyncio.sleep(POLL_INTERVAL)

        except Exception as exc:
            logger.error(f"Poll-Loop Fehler: {exc}")
            await asyncio.sleep(POLL_INTERVAL)


@app.on_event("startup")
async def startup():
    db = dashboard_db()
    db.close()
    logger.info("Dashboard-DB initialisiert")
    asyncio.create_task(_poll_loop())


def _ollama_reachable() -> bool:
    try:
        ollama_url = get_setting("ollama_url", "http://127.0.0.1:11434/api/chat")
        base = ollama_url.rsplit("/api/", 1)[0]
        r = requests.get(f"{base}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


@app.get("/health")
def health() -> dict:
    try:
        q = queue_db()
        queued = q.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0]
        failed = q.execute("SELECT COUNT(*) FROM jobs WHERE status='failed'").fetchone()[0]
        q.close()
        return {
            "ok": True,
            "service": "async-worker",
            "queued": queued,
            "failed": failed,
            "ollama": _ollama_reachable(),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/worker/run-once")
async def run_once() -> dict:
    """Manuell einen Job verarbeiten (für Tests)."""
    conn = queue_db()
    row = conn.execute(
        "SELECT id, call_id, payload FROM jobs WHERE status='queued' ORDER BY id LIMIT 1"
    ).fetchone()
    if not row:
        conn.close()
        return {"ok": True, "processed": 0}
    updated = conn.execute(
        "UPDATE jobs SET status='running', updated_at=? WHERE id=? AND status='queued'",
        (_now(), row["id"]),
    ).rowcount
    conn.commit()
    conn.close()
    if not updated:
        return {"ok": True, "processed": 0}

    ok = await asyncio.get_event_loop().run_in_executor(
        None, process_job, row["id"], row["call_id"], row["payload"]
    )
    return {"ok": ok, "processed": 1, "call_id": row["call_id"]}


@app.get("/job/status/{call_id}")
def job_status(call_id: str) -> dict:
    conn = queue_db()
    row = conn.execute(
        "SELECT status, updated_at FROM jobs WHERE call_id=?", (call_id,)
    ).fetchone()
    conn.close()
    if not row:
        return {"exists": False}
    return {"exists": True, "status": row["status"], "updated_at": row["updated_at"]}


@app.get("/leads")
def list_leads(limit: int = 50, status: str | None = None) -> dict:
    """Schnelle Lead-Übersicht direkt aus der Dashboard-DB."""
    db = dashboard_db()
    query = "SELECT id, caller_name, caller_phone_raw, address_city, description, status, urgency, created_at FROM leads"
    params = []
    if status:
        query += " WHERE status=?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = db.execute(query, params).fetchall()
    db.close()
    return {"leads": [dict(r) for r in rows]}
