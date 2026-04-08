-- =============================================================================
-- Anrufwerker — Datenbankschema v2
-- SQLite (MVP), OIDC-ready, tenant-aware, OpenCloud/Kimai-vorbereitet
-- =============================================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- -----------------------------------------------------------------------------
-- TENANTS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenants (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    slug            TEXT NOT NULL UNIQUE,           -- "malerbetrieb-dannerbeck"
    name            TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    config_path     TEXT,                           -- Pfad zur company_config JSON
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    -- OIDC: befüllen wenn SSO mit OpenCloud/Kimai gewünscht (MVP: leer)
    oidc_issuer     TEXT,
    oidc_client_id  TEXT
);

-- -----------------------------------------------------------------------------
-- USERS
-- Lokal + OIDC-fähig. password_hash NULL = nur per OIDC anmeldbar.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id       TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    password_hash   TEXT,                           -- NULL = OIDC-only
    ui_locale       TEXT NOT NULL DEFAULT 'en',
    role            TEXT NOT NULL DEFAULT 'user'
                        CHECK (role IN ('admin', 'user', 'viewer')),
    is_active       INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_login_at   TEXT,
    password_changed_at TEXT,

    -- OIDC-Identifikation (MVP: leer)
    oidc_sub        TEXT,
    oidc_issuer     TEXT,

    UNIQUE (tenant_id, email),
    UNIQUE (oidc_issuer, oidc_sub)
);

-- -----------------------------------------------------------------------------
-- USER_SESSIONS
-- Server-side Sessions. Token wird SHA-256 gehasht gespeichert.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_sessions (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    expires_at  TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at  TEXT,                               -- NULL = aktiv
    ip_address  TEXT,
    user_agent  TEXT
);

-- -----------------------------------------------------------------------------
-- API_TOKENS
-- Service-to-Service Auth (async-worker, sip-bridge, externe Tools).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_tokens (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id   TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,                      -- "async-worker", "sip-bridge"
    token_hash  TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_used_at TEXT,
    expires_at  TEXT,                               -- NULL = kein Ablauf
    revoked_at  TEXT                                -- NULL = aktiv
);

-- -----------------------------------------------------------------------------
-- CONTACTS
-- Personen/Firmen — unabhängig von einzelnen Anrufen.
-- Anrufwerker legt Leads an, nicht Kontakte direkt.
-- Kontakte entstehen manuell oder per späterer Integration.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contacts (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id       TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    display_name    TEXT NOT NULL,
    company_name    TEXT,
    phone_raw       TEXT,                           -- wie eingegeben
    phone_e164      TEXT,                           -- normalisiert: +4917612345678
    email           TEXT,
    address_street  TEXT,
    address_plz     TEXT,
    address_city    TEXT,
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    -- Stub: spätere OpenCloud/CardDAV-Verknüpfung (MVP: leer)
    opencloud_contact_id    TEXT,
    carddav_book_id         TEXT
);

-- -----------------------------------------------------------------------------
-- CALLS
-- Rohdaten jedes Anrufs. Befüllt vom async-worker nach Gesprächsende.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS calls (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id       TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    session_uuid    TEXT NOT NULL UNIQUE,           -- aus sip-bridge
    direction       TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),

    -- Nummern: raw + normalisiert für Dubletten-Erkennung
    caller_number       TEXT,
    caller_number_e164  TEXT,
    called_number       TEXT,

    started_at          TEXT NOT NULL,
    ended_at            TEXT,
    duration_seconds    INTEGER,
    turn_count          INTEGER NOT NULL DEFAULT 0,

    -- Transcript
    transcript          TEXT,                       -- JSON blob (messages array)
    transcript_path     TEXT,                       -- Pfad zur JSON-Datei
    transcript_status   TEXT NOT NULL DEFAULT 'pending'
                            CHECK (transcript_status IN ('pending', 'done', 'failed')),
    stt_provider        TEXT,                       -- "whisper-large-v3-turbo"

    -- Extraktion durch async-worker
    extraction_status   TEXT NOT NULL DEFAULT 'pending'
                            CHECK (extraction_status IN ('pending', 'running', 'done', 'failed')),
    extraction_error    TEXT,                       -- Fehlertext falls failed

    call_status         TEXT NOT NULL DEFAULT 'completed'
                            CHECK (call_status IN ('completed', 'failed', 'abandoned')),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- -----------------------------------------------------------------------------
-- LEADS
-- Strukturierte Daten aus Anrufen — via Ollama post-call extrahiert.
-- Entkoppelt von calls: ein Lead kann mehrere Anrufe umfassen.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leads (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id       TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Optionaler Kontaktbezug (nach manueller Zuordnung oder Auto-Match)
    contact_id      TEXT REFERENCES contacts(id) ON DELETE SET NULL,

    -- Extraktion
    extraction_status       TEXT NOT NULL DEFAULT 'pending'
                                CHECK (extraction_status IN ('pending', 'done', 'failed')),
    extraction_confidence   REAL,                   -- 0.0–1.0
    needs_manual_review     INTEGER NOT NULL DEFAULT 0,
    missing_fields          TEXT,                   -- JSON array: ["caller_name", "address_plz"]

    -- Kontaktdaten (aus Gespräch extrahiert)
    caller_name         TEXT,
    caller_phone_raw    TEXT,
    caller_phone_e164   TEXT,

    -- Adresse (getrennt für Routenoptimierung)
    address_street  TEXT,
    address_plz     TEXT,
    address_city    TEXT,

    -- Anliegen
    description     TEXT,
    urgency         TEXT NOT NULL DEFAULT 'normal'
                        CHECK (urgency IN ('normal', 'urgent', 'emergency')),

    -- Flags
    callback_needed INTEGER NOT NULL DEFAULT 1,
    escalated       INTEGER NOT NULL DEFAULT 0,

    -- Workflow-Status
    status          TEXT NOT NULL DEFAULT 'new'
                        CHECK (status IN (
                            'new',              -- frisch reingekommen
                            'needs_review',     -- manuelle Prüfung nötig
                            'qualified',        -- geprüft, echter Lead
                            'callback_open',    -- Rückruf steht aus
                            'scheduled',        -- Baubegehung terminiert
                            'done',             -- abgeschlossen
                            'closed_no_conversion', -- nicht zustande gekommen
                            'spam'              -- Falschverbindung / Spam
                        )),

    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

    -- Stub: spätere Kalender-Integration (MVP: leer)
    caldav_event_id         TEXT,                   -- Baubegehungs-Termin in CalDAV
    opencloud_task_id       TEXT                    -- optionale Task-Verknüpfung
);

-- -----------------------------------------------------------------------------
-- LEAD_CALLS
-- Junction-Tabelle: welche Anrufe gehören zu welchem Lead.
-- Erster Anruf erstellt den Lead (is_origin=1), Folgeanrufe ergänzen ihn.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lead_calls (
    lead_id     TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    call_id     TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    is_origin   INTEGER NOT NULL DEFAULT 0,         -- 1 = der erzeugende Anruf
    linked_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (lead_id, call_id)
);

-- -----------------------------------------------------------------------------
-- LEAD_EVENTS
-- Audit-Trail: jede Änderung wird protokolliert.
-- actor_type klar definiert: wer hat was geändert.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lead_events (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    lead_id     TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,

    -- Wer hat die Aktion ausgeführt?
    actor_type  TEXT NOT NULL
                    CHECK (actor_type IN ('system', 'ai', 'worker', 'user')),
    actor_id    TEXT,                               -- user_id oder Service-Name

    event_type  TEXT NOT NULL,                      -- "status_changed", "note_added",
                                                    -- "extraction_done", "contact_linked"
    old_value   TEXT,
    new_value   TEXT,
    payload     TEXT,                               -- JSON: beliebige Zusatzdaten

    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- -----------------------------------------------------------------------------
-- INDIZES
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
