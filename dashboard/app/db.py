import hashlib
import os
import secrets
import sqlite3
from pathlib import Path

DASHBOARD_DSN = os.getenv("DASHBOARD_DSN", "/app/data/dashboard.db")
SCHEMA_PATH = Path(__file__).parent.parent / "schema.sql"
DEFAULT_ADMIN_EMAIL = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@anrufwerker.local")
DEFAULT_ADMIN_NAME = os.getenv("DEFAULT_ADMIN_NAME", "Administrator")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "anrufwerker-start")


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DASHBOARD_DSN, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


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


def _migrate_users_table(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    if not row or not row["sql"]:
        return

    table_sql = row["sql"]
    table_info = {
        item["name"] for item in conn.execute("PRAGMA table_info(users)").fetchall()
    }
    needs_rebuild = (
        "office" in table_sql
        or "read_only" in table_sql
        or "must_change_password" not in table_info
        or "password_changed_at" not in table_info
    )
    if not needs_rebuild:
        return

    conn.execute("PRAGMA foreign_keys=OFF")
    conn.executescript(
        """
        CREATE TABLE users_new (
            id                    TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            tenant_id             TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            email                 TEXT NOT NULL,
            display_name          TEXT NOT NULL,
            password_hash         TEXT,
            role                  TEXT NOT NULL DEFAULT 'user'
                                      CHECK (role IN ('admin', 'user', 'viewer')),
            is_active             INTEGER NOT NULL DEFAULT 1,
            must_change_password  INTEGER NOT NULL DEFAULT 0,
            created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            last_login_at         TEXT,
            password_changed_at   TEXT,
            oidc_sub              TEXT,
            oidc_issuer           TEXT,
            UNIQUE (tenant_id, email),
            UNIQUE (oidc_issuer, oidc_sub)
        );

        INSERT INTO users_new (
            id, tenant_id, email, display_name, password_hash, role, is_active,
            must_change_password, created_at, last_login_at, password_changed_at,
            oidc_sub, oidc_issuer
        )
        SELECT
            id,
            tenant_id,
            email,
            display_name,
            password_hash,
            CASE
                WHEN role = 'office' THEN 'user'
                WHEN role = 'read_only' THEN 'viewer'
                WHEN role = 'admin' THEN 'admin'
                ELSE 'user'
            END,
            is_active,
            0,
            created_at,
            last_login_at,
            NULL,
            oidc_sub,
            oidc_issuer
        FROM users;

        DROP TABLE users;
        ALTER TABLE users_new RENAME TO users;
        """
    )
    conn.execute("PRAGMA foreign_keys=ON")


def _ensure_bootstrap(conn: sqlite3.Connection) -> None:
    tenant = conn.execute("SELECT id FROM tenants ORDER BY created_at ASC LIMIT 1").fetchone()
    if tenant:
        tenant_id = tenant["id"]
    else:
        tenant_id = secrets.token_hex(16)
        conn.execute(
            """
            INSERT INTO tenants (id, slug, name, config_path)
            VALUES (?, 'default', 'Anrufwerker', NULL)
            """,
            (tenant_id,),
        )

    user_count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    if user_count:
        return

    conn.execute(
        """
        INSERT INTO users (
            tenant_id, email, display_name, password_hash, role,
            is_active, must_change_password, password_changed_at
        )
        VALUES (?, ?, ?, ?, 'admin', 1, 1, NULL)
        """,
        (
            tenant_id,
            DEFAULT_ADMIN_EMAIL.lower(),
            DEFAULT_ADMIN_NAME,
            _hash_password(DEFAULT_ADMIN_PASSWORD),
        ),
    )


def init_db() -> None:
    Path(DASHBOARD_DSN).parent.mkdir(parents=True, exist_ok=True)
    conn = db()
    try:
        with conn:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            _migrate_users_table(conn)
            _ensure_bootstrap(conn)
    finally:
        conn.close()
