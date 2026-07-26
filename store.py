"""
Local persistence: users, saved datasets, saved dashboards.

Everything a person builds is scoped to their username, which is what makes
dashboards "per-person" rather than one global app state.

SQLite is used so the app runs with zero infrastructure. Swap DB_PATH for a
server-side path (or point this module at Postgres) when you deploy it.
"""

import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = os.getenv("APP_DB_PATH", "app_data.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username     TEXT PRIMARY KEY,
    display_name TEXT,
    salt         TEXT NOT NULL,
    pwd_hash     TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'analyst',
    created_at   REAL
);

CREATE TABLE IF NOT EXISTS datasets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner      TEXT NOT NULL,
    name       TEXT NOT NULL,
    source     TEXT NOT NULL,          -- 'sql' | 'csv'
    query      TEXT,                   -- SQL text, or original filename for csv
    meta       TEXT,                   -- JSON: server/database/columns
    created_at REAL,
    UNIQUE(owner, name)
);

CREATE TABLE IF NOT EXISTS dashboards (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner      TEXT NOT NULL,
    name       TEXT NOT NULL,
    spec       TEXT NOT NULL,          -- JSON dashboard spec
    shared     INTEGER NOT NULL DEFAULT 0,
    updated_at REAL,
    UNIQUE(owner, name)
);
"""


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _conn() as c:
        c.executescript(SCHEMA)


# ---------------------------------------------------------------- users

def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 120_000
    ).hex()


def user_count() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


def create_user(username, password, display_name=None, role="analyst"):
    username = username.strip().lower()
    if not username or not password:
        raise ValueError("Username and password are both required.")
    salt = secrets.token_hex(16)
    with _conn() as c:
        c.execute(
            "INSERT INTO users (username, display_name, salt, pwd_hash, role, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (username, display_name or username, salt, _hash(password, salt),
             role, time.time()),
        )


def verify_user(username, password):
    """Return the user row on success, None on failure."""
    username = (username or "").strip().lower()
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        return None
    if secrets.compare_digest(_hash(password, row["salt"]), row["pwd_hash"]):
        return dict(row)
    return None


# -------------------------------------------------------------- datasets

def save_dataset(owner, name, source, query, meta=None):
    with _conn() as c:
        c.execute(
            "INSERT INTO datasets (owner,name,source,query,meta,created_at)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(owner,name) DO UPDATE SET"
            " source=excluded.source, query=excluded.query, meta=excluded.meta",
            (owner, name, source, query, json.dumps(meta or {}), time.time()),
        )


def list_datasets(owner):
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM datasets WHERE owner=? ORDER BY name", (owner,)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_dataset(owner, name):
    with _conn() as c:
        c.execute("DELETE FROM datasets WHERE owner=? AND name=?", (owner, name))


# ------------------------------------------------------------ dashboards

def save_dashboard(owner, name, spec, shared=False):
    with _conn() as c:
        c.execute(
            "INSERT INTO dashboards (owner,name,spec,shared,updated_at)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(owner,name) DO UPDATE SET"
            " spec=excluded.spec, shared=excluded.shared, updated_at=excluded.updated_at",
            (owner, name, json.dumps(spec), int(shared), time.time()),
        )


def list_dashboards(owner, include_shared=True):
    """A person's own dashboards, plus any explicitly shared by others."""
    with _conn() as c:
        if include_shared:
            rows = c.execute(
                "SELECT * FROM dashboards WHERE owner=? OR shared=1"
                " ORDER BY owner=? DESC, name",
                (owner, owner),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM dashboards WHERE owner=? ORDER BY name", (owner,)
            ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["spec"] = json.loads(d["spec"])
        out.append(d)
    return out


def load_dashboard(owner, name):
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM dashboards WHERE owner=? AND name=?", (owner, name)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["spec"] = json.loads(d["spec"])
    return d


def delete_dashboard(owner, name):
    with _conn() as c:
        c.execute("DELETE FROM dashboards WHERE owner=? AND name=?", (owner, name))