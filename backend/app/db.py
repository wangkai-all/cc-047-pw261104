"""SQLite access layer.

A single connection per thread is enough for the demo. WAL mode keeps the
background import workers from blocking the API while they write progress.
"""
from __future__ import annotations

import sqlite3
import threading
from typing import Any

from . import config

_thread_local = threading.local()


def get_conn() -> sqlite3.Connection:
    conn = getattr(_thread_local, "conn", None)
    if conn is None:
        config.ensure_dirs()
        conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        _thread_local.conn = conn
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS import_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id    TEXT NOT NULL,
    request_id      TEXT NOT NULL,
    filename        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    mapping_json    TEXT NOT NULL,
    file_hash       TEXT NOT NULL,
    storage_path    TEXT NOT NULL,
    total_rows      INTEGER NOT NULL DEFAULT 0,
    processed_rows  INTEGER NOT NULL DEFAULT 0,
    success_rows    INTEGER NOT NULL DEFAULT 0,
    failed_rows     INTEGER NOT NULL DEFAULT 0,
    error_file_path TEXT,
    error_message   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(workspace_id, request_id)
);

-- Business key of every imported record is scoped by workspace, so the same
-- business number in two workspaces never collides.
CREATE TABLE IF NOT EXISTS records (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id   TEXT NOT NULL,
    task_id        INTEGER NOT NULL REFERENCES import_tasks(id) ON DELETE CASCADE,
    business_key   TEXT NOT NULL,
    payload_json   TEXT NOT NULL,
    row_number     INTEGER NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(workspace_id, business_key)
);

CREATE INDEX IF NOT EXISTS idx_records_ws_key ON records(workspace_id, business_key);
CREATE INDEX IF NOT EXISTS idx_tasks_ws ON import_tasks(workspace_id);
CREATE INDEX IF NOT EXISTS idx_records_task ON records(task_id);
"""


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()


def query_one(sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    cur = get_conn().execute(sql, params)
    return cur.fetchone()


def query_all(sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    cur = get_conn().execute(sql, params)
    return cur.fetchall()


def execute(sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
    conn = get_conn()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur
