-- =============================================================================
-- anrufwerker — Database schema v2
-- SQLite (MVP), OIDC-ready, tenant-aware, prepared for OpenCloud/Kimai
-- =============================================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- -----------------------------------------------------------------------------
-- TENANTS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenants (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    slug            TEXT NOT NULL UNIQUE,           -- "painting-company-smith"
    name            TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    config_path     TEXT,                           -- path to company_config JSON
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    -- OIDC: populate when SSO with OpenCloud/Kimai is desired (MVP: empty)
    oidc_issuer     TEXT,
    oidc_client_id  TEXT
);

-- -----------------------------------------------------------------------------
-- USERS
-- Local + OIDC-capable. password_hash NULL = OIDC-only login.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id       TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    password_hash   TEXT,                           -- NULL = OIDC-only
    role            TEXT NOT NULL DEFAULT 'user'
                        CHECK (role IN ('admin', 'user', 'viewer')),
    is_active       INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_login_at   TEXT,
    password_changed_at TEXT,

    -- OIDC identity fields (MVP: empty)
    oidc_sub        TEXT,
    oidc_issuer     TEXT,

    UNIQUE (tenant_id, email),
    UNIQUE (oidc_issuer, oidc_sub)
);

-- -----------------------------------------------------------------------------
-- USER_SESSIONS
-- Server-side sessions. Token is stored as SHA-256 hash.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_sessions (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    expires_at  TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at  TEXT,                               -- NULL = active
    ip_address  TEXT,
    user_agent  TEXT
);

-- -----------------------------------------------------------------------------
-- API_TOKENS
-- Service-to-service auth (async-worker, sip-bridge, external tools).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_tokens (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id   TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,                      -- "async-worker", "sip-bridge"
    token_hash  TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_used_at TEXT,
    expires_at  TEXT,                               -- NULL = no expiry
    revoked_at  TEXT                                -- NULL = active
);

-- -----------------------------------------------------------------------------
-- CONTACTS
-- Persons / companies — independent of individual calls.
-- anrufwerker creates leads, not contacts directly.
-- Contacts are created manually or via later integration.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contacts (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id       TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    display_name    TEXT NOT NULL,
    company_name    TEXT,
    phone_raw       TEXT,                           -- as entered
    phone_e164      TEXT,                           -- normalised: +4917612345678
    email           TEXT,
    address_street  TEXT,
    address_plz     TEXT,
    address_city    TEXT,
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    -- Stub: future OpenCloud/CardDAV link (MVP: empty)
    opencloud_contact_id    TEXT,
    carddav_book_id         TEXT
);

-- -----------------------------------------------------------------------------
-- CALLS
-- Raw data for every call. Populated by async-worker after the call ends.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS calls (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id       TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    session_uuid    TEXT NOT NULL UNIQUE,           -- from sip-bridge
    direction       TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),

    -- Numbers: raw + normalised for duplicate detection
    caller_number       TEXT,
    caller_number_e164  TEXT,
    called_number       TEXT,

    started_at          TEXT NOT NULL,
    ended_at            TEXT,
    duration_seconds    INTEGER,
    turn_count          INTEGER NOT NULL DEFAULT 0,

    -- Transcript
    transcript          TEXT,                       -- JSON blob (messages array)
    transcript_path     TEXT,                       -- path to JSON file
    transcript_status   TEXT NOT NULL DEFAULT 'pending'
                            CHECK (transcript_status IN ('pending', 'done', 'failed')),
    stt_provider        TEXT,                       -- "whisper-large-v3-turbo"

    -- Extraction by async-worker
    extraction_status   TEXT NOT NULL DEFAULT 'pending'
                            CHECK (extraction_status IN ('pending', 'running', 'done', 'failed')),
    extraction_error    TEXT,                       -- error text if failed

    call_status         TEXT NOT NULL DEFAULT 'completed'
                            CHECK (call_status IN ('completed', 'failed', 'abandoned')),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- -----------------------------------------------------------------------------
-- LEADS
-- Structured data from calls — extracted post-call via Ollama.
-- Decoupled from calls: one lead can span multiple calls.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leads (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id       TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Optional contact reference (after manual assignment or auto-match)
    contact_id      TEXT REFERENCES contacts(id) ON DELETE SET NULL,

    -- Extraction
    extraction_status       TEXT NOT NULL DEFAULT 'pending'
                                CHECK (extraction_status IN ('pending', 'done', 'failed')),
    extraction_confidence   REAL,                   -- 0.0–1.0
    needs_manual_review     INTEGER NOT NULL DEFAULT 0,
    missing_fields          TEXT,                   -- JSON array: ["caller_name", "address_plz"]

    -- Contact data (extracted from conversation)
    caller_name         TEXT,
    caller_phone_raw    TEXT,
    caller_phone_e164   TEXT,

    -- Address (split for route optimisation)
    address_street  TEXT,
    address_plz     TEXT,
    address_city    TEXT,

    -- Request
    description     TEXT,
    urgency         TEXT NOT NULL DEFAULT 'normal'
                        CHECK (urgency IN ('normal', 'urgent', 'emergency')),

    -- Flags
    callback_needed INTEGER NOT NULL DEFAULT 1,
    escalated       INTEGER NOT NULL DEFAULT 0,

    -- Workflow status
    status          TEXT NOT NULL DEFAULT 'new'
                        CHECK (status IN (
                            'new',                  -- just arrived
                            'needs_review',         -- requires manual review
                            'qualified',            -- reviewed, genuine lead
                            'callback_open',        -- callback pending
                            'scheduled',            -- site visit scheduled
                            'done',                 -- completed
                            'closed_no_conversion', -- did not convert
                            'spam'                  -- wrong number / spam
                        )),

    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    -- Stub: future calendar integration (MVP: empty)
    caldav_event_id         TEXT,                   -- site-visit appointment in CalDAV
    opencloud_task_id       TEXT                    -- optional task link
);

-- -----------------------------------------------------------------------------
-- LEAD_CALLS
-- Junction table: which calls belong to which lead.
-- First call creates the lead (is_origin=1), follow-up calls extend it.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lead_calls (
    lead_id     TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    call_id     TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    is_origin   INTEGER NOT NULL DEFAULT 0,         -- 1 = the originating call
    linked_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (lead_id, call_id)
);

-- -----------------------------------------------------------------------------
-- LEAD_EVENTS
-- Audit trail: every change is logged.
-- actor_type clearly defined: who changed what.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lead_events (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    lead_id     TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,

    -- Who performed the action?
    actor_type  TEXT NOT NULL
                    CHECK (actor_type IN ('system', 'ai', 'worker', 'user')),
    actor_id    TEXT,                               -- user_id or service name

    event_type  TEXT NOT NULL,                      -- "status_changed", "note_added",
                                                    -- "extraction_done", "contact_linked"
    old_value   TEXT,
    new_value   TEXT,
    payload     TEXT,                               -- JSON: arbitrary additional data

    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- -----------------------------------------------------------------------------
-- INDEXES
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_calls_tenant         ON calls(tenant_id);
CREATE INDEX IF NOT EXISTS idx_calls_started_at     ON calls(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_calls_caller_e164    ON calls(caller_number_e164);
CREATE INDEX IF NOT EXISTS idx_calls_extraction     ON calls(extraction_status);

CREATE INDEX IF NOT EXISTS idx_leads_tenant         ON leads(tenant_id);
CREATE INDEX IF NOT EXISTS idx_leads_status         ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_created_at     ON leads(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_phone_e164     ON leads(caller_phone_e164);
CREATE INDEX IF NOT EXISTS idx_leads_plz            ON leads(address_plz);
CREATE INDEX IF NOT EXISTS idx_leads_review         ON leads(needs_manual_review);
CREATE INDEX IF NOT EXISTS idx_leads_contact        ON leads(contact_id);

CREATE INDEX IF NOT EXISTS idx_lead_calls_lead      ON lead_calls(lead_id);
CREATE INDEX IF NOT EXISTS idx_lead_calls_call      ON lead_calls(call_id);

CREATE INDEX IF NOT EXISTS idx_contacts_tenant      ON contacts(tenant_id);
CREATE INDEX IF NOT EXISTS idx_contacts_phone_e164  ON contacts(phone_e164);

CREATE INDEX IF NOT EXISTS idx_sessions_token       ON user_sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_expires     ON user_sessions(expires_at);

CREATE INDEX IF NOT EXISTS idx_lead_events_lead     ON lead_events(lead_id);
CREATE INDEX IF NOT EXISTS idx_lead_events_created  ON lead_events(created_at DESC);

-- -----------------------------------------------------------------------------
-- SETTINGS
-- Admin-configurable values (model, prompt, thresholds, etc.)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL DEFAULT '',
    description TEXT,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Extraction (async-worker)
INSERT OR IGNORE INTO settings (key, value, description) VALUES
    ('ollama_url',           'http://127.0.0.1:11434/api/chat', 'Ollama API endpoint (extraction)'),
    ('ollama_model',         'mistral-small3.1:latest',          'Ollama model for extraction'),
    ('confidence_threshold', '0.6',                              'Confidence threshold for manual review (0.0–1.0)'),
    ('duration_factor',      '15',                               'Seconds per turn for duration estimate'),
    ('stt_provider',         'whisper-large-v3-turbo',           'STT provider label (display only)');

-- Phone AI (sip-bridge)
INSERT OR IGNORE INTO settings (key, value, description) VALUES
    ('llm_url',              'http://host.docker.internal:11434/api/chat', 'Ollama URL (phone AI)'),
    ('llm_model',            'ministral-3:14b-instruct-2512-q8_0',  'Ollama model for telephony'),
    ('llm_temperature',      '0.1',                 'Temperature (0.0–1.0)'),
    ('llm_top_p',            '0.85',                'Top-P (0.0–1.0)'),
    ('llm_num_predict',      '80',                  'Max. tokens per response'),
    ('llm_repeat_penalty',   '1.2',                 'Repeat penalty'),
    ('llm_num_ctx',          '2048',                'Context size');

-- Company data (company config)
INSERT OR IGNORE INTO settings (key, value, description) VALUES
    ('company_name',              '', 'Company name'),
    ('company_owner',             '', 'Owner / contact person'),
    ('company_phone_callback',    '', 'Business callback number'),
    ('company_greeting',          '', 'Bot greeting text'),
    ('company_services',          '', 'Services offered (comma-separated)'),
    ('company_opening_hours',     '', 'Opening hours'),
    ('company_escalation_message','', 'Message on escalation'),
    ('company_address',           '', 'Business address'),
    ('company_since',             '', 'Year founded'),
    ('company_employee_count',    '', 'Number of employees'),
    ('company_emergency_number',  '', 'Emergency number (optional, empty = disabled)'),
    ('company_bot_can',           'anfrage_aufnehmen,infos_geben,oeffnungszeiten', 'Bot capabilities (comma-separated)'),
    ('company_bot_cannot',        'preise_verhandeln,beschwerden,rechtliches',     'Bot limitations (comma-separated)');

INSERT OR IGNORE INTO settings (key, value, description) VALUES
    ('tts_engine',                  'piper',                     'TTS engine for telephony (piper or edge)'),
    ('tts_voice',                   'de-DE-SeraphinaMultilingualNeural', 'Edge-TTS voice (only when engine=edge)'),
    ('piper_url',                   'http://127.0.0.1:5150',    'Piper HTTP URL'),
    ('piper_voice',                 'de_DE-thorsten-high',      'Piper voice'),
    ('stt_engine',                  'whisper-http',             'STT engine'),
    ('whisper_url',                 'http://127.0.0.1:8090',    'Whisper HTTP URL'),
    ('vad_speech_frames_to_start',  '2',                        'Frames until speech start'),
    ('vad_silence_frames_to_end',   '12',                       'Silence frames until turn ends'),
    ('vad_rms_threshold',           '260',                      'RMS threshold for speech'),
    ('vad_barge_in_threshold',      '2000',                     'RMS threshold for barge-in'),
    ('vad_barge_in_frames',         '50',                       'Frames until barge-in triggers'),
    ('preroll_frames',              '8',                        'Preroll frames'),
    ('min_user_rms_process',        '150',                      'Minimum RMS for STT processing'),
    ('inactivity_timeout',          '90',                       'Timeout before hangup'),
    ('checkin_timeout',             '10',                       'Timeout before check-in prompt'),
    ('max_tts_seconds_per_sentence','10.0',                     'Max. TTS seconds per sentence'),
    ('max_tts_sentences_per_turn',  '2',                        'Max. TTS sentences per turn'),
    ('max_tts_seconds_intro',       '8.0',                      'Max. intro length in seconds'),
    ('no_regreet_after_intro',      'true',                     'Do not re-greet after intro'),
    ('process_buffered_during_llm', 'false',                    'Process buffered audio while LLM is running');
