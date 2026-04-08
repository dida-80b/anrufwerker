import asyncio
import hashlib
import html
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from .db import DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD, db, init_db

app = FastAPI(title="Anrufwerker Dashboard")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

SESSION_COOKIE = "anrufwerker_session"
SESSION_DAYS = 14
ROLE_LEVELS = {"viewer": 0, "user": 1, "admin": 2}
PUBLIC_PATHS = {"/login", "/health", "/favicon.ico"}
PASSWORD_CHANGE_ALLOWED = {"/account", "/account/password", "/logout", "/health", "/favicon.ico"}

LEAD_STATUSES = [
    ("new", "New"),
    ("needs_review", "Review"),
    ("qualified", "Qualified"),
    ("callback_open", "Callback pending"),
    ("scheduled", "Scheduled"),
    ("done", "Done"),
    ("closed_no_conversion", "No conversion"),
    ("spam", "Spam"),
]

STATUS_COLORS = {
    "new": "blue",
    "needs_review": "orange",
    "qualified": "cyan",
    "callback_open": "yellow",
    "scheduled": "violet",
    "done": "green",
    "closed_no_conversion": "slate",
    "spam": "red",
}

URGENCY_COLORS = {
    "normal": "slate",
    "urgent": "orange",
    "emergency": "red",
}

USER_ROLE_OPTIONS = [
    ("admin", "Admin"),
    ("user", "User"),
    ("viewer", "Viewer"),
]

_SETTINGS_SECTIONS = [
    {
        "id": "speech",
        "title": "Telephony / Speech",
        "description": "TTS, STT and speech endpoints for live calls.",
        "fields": [
            ("tts_engine", "TTS Engine (piper / edge)", "text"),
            ("tts_voice", "Edge-TTS Voice (only when engine=edge)", "text"),
            ("piper_url", "Piper URL", "text"),
            ("piper_voice", "Piper Voice", "text"),
            ("stt_engine", "STT Engine", "text"),
            ("whisper_url", "Whisper URL", "text"),
        ],
    },
    {
        "id": "runtime",
        "title": "Runtime / VAD",
        "description": "Thresholds and timeout behaviour during calls.",
        "fields": [
            ("vad_speech_frames_to_start", "VAD Speech Frames To Start", "text"),
            ("vad_silence_frames_to_end", "VAD Silence Frames To End", "text"),
            ("vad_rms_threshold", "VAD RMS Threshold", "text"),
            ("vad_barge_in_threshold", "VAD Barge-In Threshold", "text"),
            ("vad_barge_in_frames", "VAD Barge-In Frames", "text"),
            ("preroll_frames", "Preroll Frames", "text"),
            ("min_user_rms_process", "Min User RMS Process", "text"),
            ("inactivity_timeout", "Inactivity Timeout", "text"),
            ("checkin_timeout", "Check-In Timeout", "text"),
            ("max_tts_seconds_per_sentence", "Max TTS Seconds Per Sentence", "text"),
            ("max_tts_sentences_per_turn", "Max TTS Sentences Per Turn", "text"),
            ("max_tts_seconds_intro", "Max TTS Seconds Intro", "text"),
            ("no_regreet_after_intro", "No Regreet After Intro", "text"),
            ("process_buffered_during_llm", "Process Buffered During LLM", "text"),
        ],
    },
    {
        "id": "company",
        "title": "Company Data",
        "description": "Basic details, callback number and business profile.",
        "fields": [
            ("company_name", "Company Name", "text"),
            ("company_owner", "Owner / Contact Person", "text"),
            ("company_phone_callback", "Callback Number", "text"),
            ("company_address", "Address", "text"),
            ("company_since", "Founded", "text"),
            ("company_employee_count", "Number of Employees", "text"),
            ("company_greeting", "Greeting Text", "text"),
            ("company_services", "Services", "text"),
            ("company_opening_hours", "Opening Hours", "text"),
            ("company_escalation_message", "Escalation Message", "text"),
            ("company_emergency_number", "Emergency Number", "text"),
        ],
    },
    {
        "id": "phone-ai",
        "title": "Phone AI",
        "description": "Model, sampling and context for live telephony.",
        "fields": [
            ("llm_url", "Ollama URL", "text"),
            ("llm_model", "Model", "text"),
            ("llm_temperature", "Temperature", "text"),
            ("llm_top_p", "Top-P", "text"),
            ("llm_num_predict", "Max. Tokens", "text"),
            ("llm_repeat_penalty", "Repeat Penalty", "text"),
            ("llm_num_ctx", "Context Size", "text"),
        ],
    },
    {
        "id": "bot",
        "title": "Bot Behaviour",
        "description": "What the bot is allowed to do and what it is not.",
        "fields": [
            ("company_bot_can", "Bot can", "text"),
            ("company_bot_cannot", "Bot cannot", "text"),
        ],
    },
    {
        "id": "prompt",
        "title": "Inbound Prompt",
        "description": "Rules and tone of voice for the phone bot.",
        "fields": [
            ("system_prompt_inbound", "System Prompt", "textarea"),
        ],
    },
    {
        "id": "extraction",
        "title": "Extraction",
        "description": "Post-call parsing, confidence and prompt for the async worker.",
        "fields": [
            ("ollama_url", "Ollama URL", "text"),
            ("ollama_model", "Model", "text"),
            ("confidence_threshold", "Confidence Threshold", "text"),
            ("duration_factor", "Seconds per Turn", "text"),
            ("stt_provider", "STT Provider Label", "text"),
            ("extraction_prompt", "Extraction Prompt", "textarea"),
        ],
    },
]


@app.on_event("startup")
async def startup() -> None:
    init_db()


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    user = _get_current_user(request)
    request.state.user = user

    if path not in PUBLIC_PATHS and not user:
        return RedirectResponse(_login_redirect_target(request), status_code=303)

    if user and path == "/login":
        return RedirectResponse("/", status_code=303)

    if user and user["must_change_password"] and path not in PASSWORD_CHANGE_ALLOWED:
        return RedirectResponse("/account?forced=1", status_code=303)

    response = await call_next(request)
    return response


@app.exception_handler(PermissionError)
async def permission_error_handler(request: Request, exc: PermissionError):
    message = str(exc)
    if message == "not_authenticated":
      return RedirectResponse(_login_redirect_target(request), status_code=303)
    return HTMLResponse("Access denied", status_code=403)


def _login_redirect_target(request: Request) -> str:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return f"/login?{urlencode({'next': next_path})}"


def _fmt_ts(ts: str | None) -> str:
    if not ts:
        return "—"
    try:
        date, time = ts[:16].split("T")
        _, month, day = date.split("-")
        return f"{day}.{month}. {time}"
    except Exception:
        return ts[:16]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    iterations = 240_000
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def _verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        algorithm, iterations, salt, digest = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        ).hex()
        return secrets.compare_digest(candidate, digest)
    except Exception:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _get_current_user(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None

    conn = db()
    try:
        row = conn.execute(
            """
            SELECT
                u.id,
                u.email,
                u.display_name,
                u.role,
                u.is_active,
                u.must_change_password,
                u.password_changed_at,
                u.tenant_id,
                t.name AS tenant_name,
                s.id AS session_id
            FROM user_sessions s
            JOIN users u ON u.id = s.user_id
            LEFT JOIN tenants t ON t.id = u.tenant_id
            WHERE s.token_hash = ?
              AND s.revoked_at IS NULL
              AND datetime(s.expires_at) > datetime('now')
              AND u.is_active = 1
            """,
            (_token_hash(token),),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE user_sessions SET last_used_at=? WHERE id=?",
            (_utc_now(), row["session_id"]),
        )
        return dict(row)
    finally:
        conn.close()


def _require_role(request: Request, role: str = "viewer") -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise PermissionError("not_authenticated")
    if ROLE_LEVELS[user["role"]] < ROLE_LEVELS[role]:
        raise PermissionError("forbidden")
    return user


def _render(request: Request, template_name: str, context: dict, status_code: int = 200):
    base_context = {
        "request": request,
        "current_user": getattr(request.state, "user", None),
        "role_labels": dict(USER_ROLE_OPTIONS),
    }
    base_context.update(context)
    return templates.TemplateResponse(template_name, base_context, status_code=status_code)


def _set_session(response: RedirectResponse, user_id: str, request: Request) -> None:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    conn = db()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO user_sessions (
                    user_id, token_hash, expires_at, last_used_at, ip_address, user_agent
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    _token_hash(token),
                    expires.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                    _utc_now(),
                    request.client.host if request.client else None,
                    request.headers.get("user-agent", ""),
                ),
            )
            conn.execute(
                "UPDATE users SET last_login_at=? WHERE id=?",
                (_utc_now(), user_id),
            )
    finally:
        conn.close()

    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        path="/",
    )


def _clear_session(request: Request, response: RedirectResponse) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        conn = db()
        try:
            with conn:
                conn.execute(
                    "UPDATE user_sessions SET revoked_at=? WHERE token_hash=?",
                    (_utc_now(), _token_hash(token)),
                )
        finally:
            conn.close()
    response.delete_cookie(SESSION_COOKIE, path="/")


def _load_settings() -> dict:
    conn = db()
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
    except Exception:
        return {}
    finally:
        conn.close()


def _load_index_data(status: str = "", q: str = "") -> dict:
    conn = db()
    try:
        stats = {}
        for status_key, _ in LEAD_STATUSES:
            stats[status_key] = conn.execute(
                "SELECT COUNT(*) FROM leads WHERE status=?",
                (status_key,),
            ).fetchone()[0]

        stats["total"] = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        stats["today"] = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE date(created_at)=date('now')"
        ).fetchone()[0]
        stats["review"] = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE needs_manual_review=1"
        ).fetchone()[0]
        stats["urgent"] = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE urgency IN ('urgent', 'emergency')"
        ).fetchone()[0]

        query = """
            SELECT l.id, l.caller_name, l.caller_phone_raw, l.address_city,
                   l.address_plz, l.description, l.urgency, l.status,
                   l.needs_manual_review, l.extraction_confidence,
                   l.callback_needed, l.created_at, l.updated_at,
                   t.name AS tenant_name
            FROM leads l
            LEFT JOIN tenants t ON t.id = l.tenant_id
            WHERE 1=1
        """
        params: list[str] = []
        if status:
            query += " AND l.status=?"
            params.append(status)
        if q:
            query += """
                AND (
                    lower(coalesce(l.caller_name, '')) LIKE ?
                    OR lower(coalesce(l.caller_phone_raw, '')) LIKE ?
                    OR lower(coalesce(l.address_city, '')) LIKE ?
                    OR lower(coalesce(l.description, '')) LIKE ?
                )
            """
            like_q = f"%{q.lower()}%"
            params.extend([like_q, like_q, like_q, like_q])
        query += " ORDER BY l.created_at DESC LIMIT 150"

        leads = [dict(r) for r in conn.execute(query, params).fetchall()]
        for lead in leads:
            lead["created_fmt"] = _fmt_ts(lead["created_at"])
            lead["updated_fmt"] = _fmt_ts(lead["updated_at"])

        return {
            "leads": leads,
            "stats": stats,
            "highlights": {
                "open": stats["new"] + stats["needs_review"] + stats["callback_open"],
                "review": stats["review"],
                "urgent": stats["urgent"],
                "today": stats["today"],
            },
        }
    finally:
        conn.close()


def _load_lead_detail(lead_id: str) -> dict | None:
    conn = db()
    lead = conn.execute(
        """
        SELECT l.*, t.name AS tenant_name
        FROM leads l
        LEFT JOIN tenants t ON t.id = l.tenant_id
        WHERE l.id=?
        """,
        (lead_id,),
    ).fetchone()
    if not lead:
        conn.close()
        return None

    lead = dict(lead)
    calls = [
        dict(c)
        for c in conn.execute(
            """
            SELECT c.id, c.session_uuid, c.direction, c.caller_number,
                   c.started_at, c.duration_seconds, c.turn_count,
                   c.transcript, c.extraction_status, lc.is_origin
            FROM calls c
            JOIN lead_calls lc ON lc.call_id = c.id
            WHERE lc.lead_id=?
            ORDER BY c.started_at DESC
            """,
            (lead_id,),
        ).fetchall()
    ]
    events = [
        dict(e)
        for e in conn.execute(
            """
            SELECT event_type, actor_type, actor_id, old_value, new_value, payload, created_at
            FROM lead_events
            WHERE lead_id=?
            ORDER BY created_at ASC
            """,
            (lead_id,),
        ).fetchall()
    ]
    conn.close()

    for call in calls:
        raw = call.get("transcript")
        try:
            call["messages"] = json.loads(raw) if raw else []
        except Exception:
            call["messages"] = []
        call["started_fmt"] = _fmt_ts(call["started_at"])

    for event in events:
        event["created_fmt"] = _fmt_ts(event["created_at"])

    mf = lead.get("missing_fields")
    try:
        lead["missing_fields_list"] = json.loads(mf) if mf else []
    except Exception:
        lead["missing_fields_list"] = []

    lead["created_fmt"] = _fmt_ts(lead["created_at"])
    lead["updated_fmt"] = _fmt_ts(lead.get("updated_at"))
    return {"lead": lead, "calls": calls, "events": events}


def _render_events_fragment(lead_id: str) -> str:
    conn = db()
    try:
        events = conn.execute(
            """
            SELECT event_type, actor_id, created_at, new_value
            FROM lead_events
            WHERE lead_id=?
            ORDER BY created_at ASC
            """,
            (lead_id,),
        ).fetchall()
    finally:
        conn.close()

    items = []
    for event in events:
        ts_fmt = _fmt_ts(event["created_at"])
        actor = event["actor_id"] or "system"
        if event["event_type"] == "note_added":
            text = f"Note added: {event['new_value']}"
        elif event["event_type"] == "status_changed":
            text = f"Status changed to {dict(LEAD_STATUSES).get(event['new_value'], event['new_value'])}"
        else:
            text = event["event_type"]
        items.append(
            f'<li class="timeline-item"><small>{html.escape(ts_fmt)}</small><strong>{html.escape(actor)}</strong><span>{html.escape(text)}</span></li>'
        )
    return f'<ul id="event-list" class="timeline">{"".join(items)}</ul>'


def _load_users() -> list[dict]:
    conn = db()
    try:
        rows = conn.execute(
            """
            SELECT u.id, u.email, u.display_name, u.role, u.is_active,
                   u.must_change_password, u.created_at, u.last_login_at,
                   t.name AS tenant_name
            FROM users u
            LEFT JOIN tenants t ON t.id = u.tenant_id
            ORDER BY CASE u.role WHEN 'admin' THEN 0 WHEN 'user' THEN 1 ELSE 2 END,
                     lower(u.display_name), lower(u.email)
            """
        ).fetchall()
        users = [dict(row) for row in rows]
        for user in users:
            user["created_fmt"] = _fmt_ts(user["created_at"])
            user["last_login_fmt"] = _fmt_ts(user["last_login_at"])
        return users
    finally:
        conn.close()


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/", error: str = "", seeded: str = ""):
    return _render(
        request,
        "login.html",
        {
            "next": next or "/",
            "error": error,
            "seeded": seeded == "1",
            "default_admin_email": DEFAULT_ADMIN_EMAIL,
        },
    )


@app.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form("/")):
    conn = db()
    try:
        user = conn.execute(
            """
            SELECT id, email, display_name, password_hash, role, is_active
            FROM users
            WHERE lower(email)=lower(?)
            """,
            (email.strip(),),
        ).fetchone()
    finally:
        conn.close()

    if not user or not user["is_active"] or not _verify_password(password, user["password_hash"]):
        params = urlencode({"error": "Login failed", "next": next or "/"})
        return RedirectResponse(f"/login?{params}", status_code=303)

    response = RedirectResponse(next or "/", status_code=303)
    _set_session(response, user["id"], request)
    return response


@app.post("/logout")
async def logout(request: Request):
    response = RedirectResponse("/login", status_code=303)
    _clear_session(request, response)
    return response


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, status: str = "", q: str = ""):
    _require_role(request, "viewer")
    data = _load_index_data(status=status, q=q.strip())
    return _render(
        request,
        "index.html",
        {
            "leads": data["leads"],
            "stats": data["stats"],
            "highlights": data["highlights"],
            "statuses": LEAD_STATUSES,
            "status_colors": STATUS_COLORS,
            "urgency_colors": URGENCY_COLORS,
            "active_filter": status,
            "query": q.strip(),
        },
    )


@app.get("/partial/anfragen", response_class=HTMLResponse)
async def partial_leads(request: Request, status: str = "", q: str = ""):
    _require_role(request, "viewer")
    data = _load_index_data(status=status, q=q.strip())
    return _render(
        request,
        "partial_anfragen.html",
        {
            "leads": data["leads"],
            "stats": data["stats"],
            "highlights": data["highlights"],
            "statuses": LEAD_STATUSES,
            "status_colors": STATUS_COLORS,
            "urgency_colors": URGENCY_COLORS,
            "active_filter": status,
            "query": q.strip(),
        },
    )


@app.get("/lead/{lead_id}", response_class=HTMLResponse)
async def lead_detail(request: Request, lead_id: str):
    _require_role(request, "viewer")
    data = _load_lead_detail(lead_id)
    if not data:
        return HTMLResponse("<h2>Lead not found</h2>", status_code=404)
    return _render(
        request,
        "lead_detail.html",
        {
            **data,
            "statuses": LEAD_STATUSES,
            "status_colors": STATUS_COLORS,
            "urgency_colors": URGENCY_COLORS,
            "can_edit": ROLE_LEVELS[request.state.user["role"]] >= ROLE_LEVELS["user"],
        },
    )


@app.post("/lead/{lead_id}/status", response_class=HTMLResponse)
async def update_status(request: Request, lead_id: str, status: str = Form(...)):
    user = _require_role(request, "user")
    valid_statuses = {key for key, _ in LEAD_STATUSES}
    if status not in valid_statuses:
        return HTMLResponse("Invalid status", status_code=400)

    conn = db()
    try:
        with conn:
            old = conn.execute("SELECT status FROM leads WHERE id=?", (lead_id,)).fetchone()
            if not old:
                return HTMLResponse("Not found", status_code=404)
            conn.execute(
                "UPDATE leads SET status=?, updated_at=? WHERE id=?",
                (status, _utc_now(), lead_id),
            )
            conn.execute(
                """
                INSERT INTO lead_events
                    (lead_id, actor_type, actor_id, event_type, old_value, new_value)
                VALUES (?, 'user', ?, 'status_changed', ?, ?)
                """,
                (lead_id, user["email"], old["status"], status),
            )
    finally:
        conn.close()

    label = dict(LEAD_STATUSES).get(status, status)
    color = STATUS_COLORS.get(status, "slate")
    return HTMLResponse(
        f"""
        <span class="status-badge-wrap" id="status-badge-{lead_id}">
          <span class="badge" data-color="{color}">{label}</span>
        </span>
        """
    )


@app.post("/lead/{lead_id}/note", response_class=HTMLResponse)
async def add_note(request: Request, lead_id: str, note: str = Form(...)):
    user = _require_role(request, "user")
    note = note.strip()
    if not note:
        return HTMLResponse("", status_code=200)

    conn = db()
    try:
        with conn:
            existing = conn.execute("SELECT notes FROM leads WHERE id=?", (lead_id,)).fetchone()
            if not existing:
                return HTMLResponse("Not found", status_code=404)
            ts = datetime.now(timezone.utc).strftime("%d.%m. %H:%M")
            old_notes = existing["notes"] or ""
            new_notes = f"{old_notes}\n[{ts}] {note}".strip()
            conn.execute(
                "UPDATE leads SET notes=?, updated_at=? WHERE id=?",
                (new_notes, _utc_now(), lead_id),
            )
            conn.execute(
                """
                INSERT INTO lead_events
                    (lead_id, actor_type, actor_id, event_type, new_value)
                VALUES (?, 'user', ?, 'note_added', ?)
                """,
                (lead_id, user["email"], note),
            )
    finally:
        conn.close()

    events_html = _render_events_fragment(lead_id)
    return HTMLResponse(
        f"""
        {events_html}
        <form class="note-form"
              hx-post="/lead/{lead_id}/note"
              hx-target="#notes-panel"
              hx-swap="innerHTML"
              hx-on::after-request="this.reset()">
          <input type="text" name="note" placeholder="Add note" autocomplete="off">
          <button type="submit">Save</button>
        </form>
        """
    )


@app.get("/account", response_class=HTMLResponse)
async def account(request: Request, saved: str = "", error: str = "", forced: str = ""):
    user = _require_role(request, "viewer")
    return _render(
        request,
        "account.html",
        {
            "saved": saved == "1",
            "error": error,
            "forced": forced == "1" or bool(user["must_change_password"]),
        },
    )


@app.post("/account/password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    user = _require_role(request, "viewer")
    if new_password != confirm_password:
        return RedirectResponse("/account?error=Passwords%20do%20not%20match", status_code=303)
    if len(new_password) < 10:
        return RedirectResponse("/account?error=Password%20too%20short", status_code=303)

    conn = db()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id=?",
            (user["id"],),
        ).fetchone()
        if not row or not _verify_password(current_password, row["password_hash"]):
            return RedirectResponse("/account?error=Current%20password%20is%20incorrect", status_code=303)
        with conn:
            conn.execute(
                """
                UPDATE users
                SET password_hash=?, must_change_password=0, password_changed_at=?
                WHERE id=?
                """,
                (_hash_password(new_password), _utc_now(), user["id"]),
            )
    finally:
        conn.close()

    return RedirectResponse("/account?saved=1", status_code=303)


@app.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, saved: str = ""):
    _require_role(request, "admin")
    settings = _load_settings()
    return _render(
        request,
        "admin_settings.html",
        {
            "settings": settings,
            "sections": _SETTINGS_SECTIONS,
            "saved": saved == "1",
        },
    )


@app.post("/admin/settings")
async def save_settings(request: Request):
    _require_role(request, "admin")
    form = await request.form()
    conn = db()
    try:
        with conn:
            for key, value in form.items():
                conn.execute(
                    """
                    INSERT INTO settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value,
                        updated_at=excluded.updated_at
                    """,
                    (key, value.strip() if isinstance(value, str) else value, _utc_now()),
                )
    finally:
        conn.close()
    return RedirectResponse("/admin/settings?saved=1", status_code=303)


@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request, saved: str = "", error: str = ""):
    _require_role(request, "admin")
    return _render(
        request,
        "admin_users.html",
        {
            "users": _load_users(),
            "saved": saved == "1",
            "error": error,
            "role_options": USER_ROLE_OPTIONS,
            "default_password": DEFAULT_ADMIN_PASSWORD,
        },
    )


@app.post("/admin/users")
async def create_user(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    role: str = Form(...),
    password: str = Form(...),
):
    current_user = _require_role(request, "admin")
    if role not in dict(USER_ROLE_OPTIONS):
        return RedirectResponse("/admin/users?error=Invalid%20role", status_code=303)
    if len(password) < 10:
        return RedirectResponse("/admin/users?error=Password%20too%20short", status_code=303)

    conn = db()
    try:
        tenant_id = current_user["tenant_id"]
        with conn:
            conn.execute(
                """
                INSERT INTO users (
                    tenant_id, email, display_name, password_hash, role, is_active,
                    must_change_password, password_changed_at
                )
                VALUES (?, ?, ?, ?, ?, 1, 1, NULL)
                """,
                (
                    tenant_id,
                    email.strip().lower(),
                    display_name.strip(),
                    _hash_password(password),
                    role,
                ),
            )
    except Exception:
        return RedirectResponse("/admin/users?error=Failed%20to%20create%20user", status_code=303)
    finally:
        conn.close()
    return RedirectResponse("/admin/users?saved=1", status_code=303)


@app.post("/admin/users/{user_id}/role")
async def update_user_role(request: Request, user_id: str, role: str = Form(...)):
    current_user = _require_role(request, "admin")
    if role not in dict(USER_ROLE_OPTIONS):
        return RedirectResponse("/admin/users?error=Invalid%20role", status_code=303)
    if user_id == current_user["id"] and role != "admin":
        return RedirectResponse("/admin/users?error=Cannot%20remove%20your%20own%20admin%20access", status_code=303)

    conn = db()
    try:
        with conn:
            conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    finally:
        conn.close()
    return RedirectResponse("/admin/users?saved=1", status_code=303)


@app.post("/admin/users/{user_id}/toggle")
async def toggle_user_active(request: Request, user_id: str):
    current_user = _require_role(request, "admin")
    if user_id == current_user["id"]:
        return RedirectResponse("/admin/users?error=Cannot%20deactivate%20your%20own%20account", status_code=303)

    conn = db()
    try:
        with conn:
            row = conn.execute("SELECT is_active FROM users WHERE id=?", (user_id,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET is_active=? WHERE id=?",
                    (0 if row["is_active"] else 1, user_id),
                )
    finally:
        conn.close()
    return RedirectResponse("/admin/users?saved=1", status_code=303)


@app.post("/admin/users/{user_id}/reset-password")
async def reset_user_password(request: Request, user_id: str, password: str = Form(...)):
    _require_role(request, "admin")
    if len(password) < 10:
        return RedirectResponse("/admin/users?error=Password%20too%20short", status_code=303)

    conn = db()
    try:
        with conn:
            conn.execute(
                """
                UPDATE users
                SET password_hash=?, must_change_password=1, password_changed_at=NULL
                WHERE id=?
                """,
                (_hash_password(password), user_id),
            )
            conn.execute(
                "UPDATE user_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (_utc_now(), user_id),
            )
    finally:
        conn.close()
    return RedirectResponse("/admin/users?saved=1", status_code=303)


@app.get("/sse/anfragen")
async def sse_anfragen(request: Request):
    _require_role(request, "viewer")

    async def generator():
        conn = db()
        try:
            last_max = conn.execute("SELECT MAX(rowid) FROM leads").fetchone()[0] or 0
        finally:
            conn.close()
        yield {"event": "ping", "data": ""}
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(3)
            try:
                conn = db()
                current_max = conn.execute("SELECT MAX(rowid) FROM leads").fetchone()[0] or 0
                conn.close()
                if current_max != last_max:
                    last_max = current_max
                    yield {"event": "refresh", "data": ""}
            except Exception:
                pass

    return EventSourceResponse(generator())


@app.get("/health")
def health():
    try:
        init_db()
        conn = db()
        n = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        conn.close()
        return {"ok": True, "leads": n, "users": users}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
