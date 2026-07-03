"""SQLite storage layer.

The queue is backed by a single SQLite database. We use WAL mode so readers
(the API) don't block the writers (the workers), and a process-wide lock to make
job *claiming* atomic across worker threads. Everything else relies on SQLite's
own row-level atomicity.
"""

import os
import sqlite3
import threading

DB_PATH = os.environ.get(
    "JOBQUEUE_DB",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "jobs.db"),
)

# Guards the read-modify-write cycle in `claim_next`. All workers live in one
# process, so a plain threading.Lock is enough to prevent two workers grabbing
# the same job.
claim_lock = threading.Lock()

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    queue           TEXT NOT NULL DEFAULT 'default',
    task            TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}',
    priority        INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'queued',
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    available_at    REAL NOT NULL,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    started_at      REAL,
    finished_at     REAL,
    runtime_ms      REAL,
    result          TEXT,
    error           TEXT,
    idempotency_key TEXT,
    worker_id       TEXT
);

-- Enforces idempotency: a second enqueue with the same key is a no-op.
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idem
    ON jobs(idempotency_key) WHERE idempotency_key IS NOT NULL;

-- Speeds up the hot claim query.
CREATE INDEX IF NOT EXISTS idx_jobs_claim
    ON jobs(status, available_at, priority);

CREATE INDEX IF NOT EXISTS idx_jobs_finished ON jobs(finished_at);
"""


def get_conn() -> sqlite3.Connection:
    """Return a thread-local connection (SQLite connections aren't shareable)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()


def reset_db() -> None:
    """Drop all jobs — used by tests and the /api/admin/reset endpoint."""
    conn = get_conn()
    conn.execute("DELETE FROM jobs")
    conn.commit()
