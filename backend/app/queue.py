"""Queue operations: the heart of the system.

Delivery model: **at-least-once**. A job is claimed (marked active + attempts
incremented) before it runs, so a crash mid-execution leaves it recoverable, but
it may run more than once — hence idempotency keys on enqueue and the advice to
make handlers idempotent.

Job lifecycle:

    queued ──claim──> active ──success──> completed
       ^                 │
       │                 └──failure, attempts<max──> retrying ──(available_at)──> claim
       │                 └──failure, attempts>=max──> dead   (dead-letter queue)
    retrying ──available_at reached──> (claimable again)

`scheduled`/`delayed` is not a separate status — it's simply a queued/retrying
job whose `available_at` is in the future.
"""

import json
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from . import db

# Statuses that a worker may pick up (once available_at has passed).
CLAIMABLE = ("queued", "retrying")
ACTIVE = "active"


def _now() -> float:
    return time.time()


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    d["payload"] = json.loads(d["payload"]) if d.get("payload") else {}
    if d.get("result"):
        try:
            d["result"] = json.loads(d["result"])
        except (json.JSONDecodeError, TypeError):
            pass
    now = _now()
    # Convenience flag for the UI: a claimable job not yet due is "scheduled".
    d["delayed"] = d["status"] in CLAIMABLE and (d["available_at"] or 0) > now
    return d


# --------------------------------------------------------------------------- #
# Enqueue
# --------------------------------------------------------------------------- #

def enqueue(
    task: str,
    payload: Optional[Dict[str, Any]] = None,
    queue: str = "default",
    priority: int = 0,
    max_attempts: int = 3,
    delay_seconds: float = 0,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    conn = db.get_conn()

    if idempotency_key:
        existing = conn.execute(
            "SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if existing:
            return _row_to_dict(existing) | {"deduplicated": True}

    now = _now()
    job_id = uuid.uuid4().hex
    available_at = now + max(0.0, float(delay_seconds))
    conn.execute(
        """INSERT INTO jobs
           (id, queue, task, payload, priority, status, attempts, max_attempts,
            available_at, created_at, updated_at, idempotency_key)
           VALUES (?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?)""",
        (
            job_id, queue, task, json.dumps(payload or {}), priority,
            max_attempts, available_at, now, now, idempotency_key,
        ),
    )
    conn.commit()
    return _row_to_dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


# --------------------------------------------------------------------------- #
# Claim — atomic, concurrency-aware
# --------------------------------------------------------------------------- #

def claim_next(worker_id: str, get_limit: Callable[[str], int]) -> Optional[Dict[str, Any]]:
    """Atomically claim the highest-priority due job, respecting per-queue
    concurrency limits. Returns the claimed job or None."""
    with db.claim_lock:
        conn = db.get_conn()
        now = _now()
        candidates = conn.execute(
            f"""SELECT * FROM jobs
                WHERE status IN {CLAIMABLE} AND available_at <= ?
                ORDER BY priority DESC, available_at ASC, created_at ASC
                LIMIT 50""",
            (now,),
        ).fetchall()

        # Track how many active slots each queue has already used this pass.
        active_counts: Dict[str, int] = {}
        for job in candidates:
            q = job["queue"]
            if q not in active_counts:
                active_counts[q] = conn.execute(
                    "SELECT COUNT(*) FROM jobs WHERE queue = ? AND status = ?",
                    (q, ACTIVE),
                ).fetchone()[0]
            if active_counts[q] >= get_limit(q):
                continue  # queue is saturated; try the next candidate

            cur = conn.execute(
                """UPDATE jobs
                   SET status = ?, attempts = attempts + 1, started_at = ?,
                       finished_at = NULL, worker_id = ?, updated_at = ?
                   WHERE id = ? AND status = ?""",
                (ACTIVE, now, worker_id, now, job["id"], job["status"]),
            )
            if cur.rowcount == 1:
                conn.commit()
                return _row_to_dict(
                    conn.execute("SELECT * FROM jobs WHERE id = ?", (job["id"],)).fetchone()
                )
        return None


# --------------------------------------------------------------------------- #
# Completion / failure
# --------------------------------------------------------------------------- #

def complete_job(job_id: str, result: Any) -> None:
    conn = db.get_conn()
    now = _now()
    row = conn.execute("SELECT started_at FROM jobs WHERE id = ?", (job_id,)).fetchone()
    runtime_ms = (now - row["started_at"]) * 1000 if row and row["started_at"] else None
    conn.execute(
        """UPDATE jobs
           SET status = 'completed', result = ?, error = NULL,
               finished_at = ?, runtime_ms = ?, updated_at = ?
           WHERE id = ?""",
        (json.dumps(result, default=str), now, runtime_ms, now, job_id),
    )
    conn.commit()


def fail_job(job_id: str, error: str, backoff_base: float, backoff_cap: float) -> Dict[str, Any]:
    """Record a failed attempt. Retries with exponential backoff + full jitter
    until max_attempts is hit, then moves the job to the dead-letter queue."""
    import random

    conn = db.get_conn()
    now = _now()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        return {}

    attempts = job["attempts"]  # already incremented at claim time
    runtime_ms = (now - job["started_at"]) * 1000 if job["started_at"] else None

    if attempts >= job["max_attempts"]:
        conn.execute(
            """UPDATE jobs SET status = 'dead', error = ?, finished_at = ?,
                   runtime_ms = ?, updated_at = ? WHERE id = ?""",
            (error, now, runtime_ms, now, job_id),
        )
        conn.commit()
        return {"status": "dead", "attempts": attempts}

    # Exponential backoff with full jitter: sleep in [0, base * 2^(attempt-1)].
    ceil = min(backoff_cap, backoff_base * (2 ** (attempts - 1)))
    delay = random.uniform(0, ceil)
    conn.execute(
        """UPDATE jobs SET status = 'retrying', error = ?, available_at = ?,
               runtime_ms = ?, updated_at = ? WHERE id = ?""",
        (error, now + delay, runtime_ms, now, job_id),
    )
    conn.commit()
    return {"status": "retrying", "attempts": attempts, "retry_in_seconds": round(delay, 2)}


# --------------------------------------------------------------------------- #
# Recovery — for crashed / interrupted workers
# --------------------------------------------------------------------------- #

def requeue_stuck_active(older_than_seconds: float = 0) -> int:
    """On startup, any job still marked `active` belongs to a worker that died.
    Send it back to `queued` (attempts is preserved, so it still counts)."""
    conn = db.get_conn()
    now = _now()
    cur = conn.execute(
        """UPDATE jobs SET status = 'queued', available_at = ?, worker_id = NULL,
               updated_at = ? WHERE status = 'active' AND updated_at <= ?""",
        (now, now, now - older_than_seconds),
    )
    conn.commit()
    return cur.rowcount


# --------------------------------------------------------------------------- #
# Admin / UI operations
# --------------------------------------------------------------------------- #

def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    row = db.get_conn().execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_jobs(
    status: Optional[str] = None,
    queue: Optional[str] = None,
    task: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    clauses, params = [], []
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        clauses.append(f"status IN ({','.join('?' * len(statuses))})")
        params.extend(statuses)
    if queue:
        clauses.append("queue = ?")
        params.append(queue)
    if task:
        clauses.append("task = ?")
        params.append(task)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([min(limit, 500), offset])
    rows = db.get_conn().execute(
        f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", params
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def retry_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Re-drive a dead (or otherwise finished) job. Resets attempts."""
    conn = db.get_conn()
    now = _now()
    cur = conn.execute(
        """UPDATE jobs SET status = 'queued', attempts = 0, error = NULL,
               result = NULL, available_at = ?, started_at = NULL,
               finished_at = NULL, updated_at = ? WHERE id = ?""",
        (now, now, job_id),
    )
    conn.commit()
    return get_job(job_id) if cur.rowcount else None


def delete_job(job_id: str) -> bool:
    conn = db.get_conn()
    cur = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()
    return cur.rowcount > 0


def purge(status: Optional[str] = None) -> int:
    conn = db.get_conn()
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        cur = conn.execute(
            f"DELETE FROM jobs WHERE status IN ({','.join('?' * len(statuses))})", statuses
        )
    else:
        cur = conn.execute("DELETE FROM jobs")
    conn.commit()
    return cur.rowcount


# --------------------------------------------------------------------------- #
# Stats for the monitoring dashboard
# --------------------------------------------------------------------------- #

def stats(window_seconds: int = 120, bucket_seconds: int = 5) -> Dict[str, Any]:
    conn = db.get_conn()
    now = _now()

    counts = {r["status"]: r["n"] for r in conn.execute(
        "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
    ).fetchall()}
    for s in ("queued", "active", "retrying", "completed", "dead"):
        counts.setdefault(s, 0)

    scheduled = conn.execute(
        f"SELECT COUNT(*) FROM jobs WHERE status IN {CLAIMABLE} AND available_at > ?",
        (now,),
    ).fetchone()[0]

    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    finished = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status IN ('completed','dead')"
    ).fetchone()[0]
    completed_total = counts["completed"]
    success_rate = (completed_total / finished) if finished else None

    avg_runtime = conn.execute(
        "SELECT AVG(runtime_ms) FROM jobs WHERE status = 'completed' AND runtime_ms IS NOT NULL"
    ).fetchone()[0]

    # Throughput time-series over the trailing window.
    start = now - window_seconds
    rows = conn.execute(
        """SELECT finished_at, status FROM jobs
           WHERE finished_at >= ? AND status IN ('completed','dead')""",
        (start,),
    ).fetchall()
    n_buckets = window_seconds // bucket_seconds
    series = [
        {"t": round(start + i * bucket_seconds, 1), "completed": 0, "failed": 0}
        for i in range(n_buckets)
    ]
    for r in rows:
        idx = int((r["finished_at"] - start) // bucket_seconds)
        if 0 <= idx < n_buckets:
            key = "completed" if r["status"] == "completed" else "failed"
            series[idx][key] += 1

    return {
        "counts": counts,
        "scheduled": scheduled,
        "total": total,
        "success_rate": success_rate,
        "avg_runtime_ms": round(avg_runtime, 1) if avg_runtime else None,
        "throughput_per_min": sum(s["completed"] for s in series) / (window_seconds / 60),
        "series": series,
        "bucket_seconds": bucket_seconds,
        "now": now,
    }


def queue_names() -> List[str]:
    rows = db.get_conn().execute("SELECT DISTINCT queue FROM jobs").fetchall()
    return [r["queue"] for r in rows]


def queue_counts() -> Dict[str, Dict[str, int]]:
    rows = db.get_conn().execute(
        "SELECT queue, status, COUNT(*) AS n FROM jobs GROUP BY queue, status"
    ).fetchall()
    out: Dict[str, Dict[str, int]] = {}
    for r in rows:
        out.setdefault(r["queue"], {})[r["status"]] = r["n"]
    return out
