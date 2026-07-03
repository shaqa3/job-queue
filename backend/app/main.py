"""FastAPI application: REST API + worker lifecycle.

The worker pool is started/stopped via the ASGI lifespan, so `uvicorn` handles
graceful shutdown (SIGINT/SIGTERM -> drain in-flight jobs) for free.
"""

import asyncio
import json
import os
import random
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import db
from . import queue as q
from . import tasks
from .hub import Hub
from .models import EnqueueRequest, QueueLimitRequest, SeedRequest
from .worker import WorkerPool

# Per-queue concurrency limits for the demo. Any queue not listed uses the
# pool default. 'default' is generous; 'reports' is deliberately throttled to 1
# to make the concurrency limit visible in the UI.
DEFAULT_LIMITS = {"default": 6, "emails": 3, "reports": 1}

pool = WorkerPool(
    num_workers=int(os.environ.get("JOBQUEUE_WORKERS", "6")),
    default_concurrency=int(os.environ.get("JOBQUEUE_DEFAULT_CONCURRENCY", "5")),
    queue_limits=DEFAULT_LIMITS,
    backoff_base=float(os.environ.get("JOBQUEUE_BACKOFF_BASE", "2.0")),
    backoff_cap=float(os.environ.get("JOBQUEUE_BACKOFF_CAP", "30.0")),
)

hub = Hub()


def _queues_list():
    counts = q.queue_counts()
    names = sorted(set(list(counts.keys()) + list(DEFAULT_LIMITS.keys())))
    return [
        {"name": n, "concurrency": pool.get_limit(n), "counts": counts.get(n, {})}
        for n in names
    ]


def _build_common() -> Dict[str, Any]:
    """Shared parts of a live snapshot — computed once per broadcast."""
    return {"stats": q.stats(), "queues": _queues_list(), "workers": pool.status()}


def _build_jobs(status: Optional[str]):
    return q.list_jobs(status=status, limit=100)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    hub.bind(asyncio.get_running_loop(), _build_common, _build_jobs)
    pool.on_change = hub.notify  # push a WS update whenever a job changes state
    pool.start()
    broadcaster = asyncio.create_task(hub.run())
    try:
        yield
    finally:
        broadcaster.cancel()
        pool.shutdown(drain_timeout=float(os.environ.get("JOBQUEUE_DRAIN_TIMEOUT", "30")))


app = FastAPI(title="Job Queue + Monitoring", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Live feed (WebSocket)
# --------------------------------------------------------------------------- #

@app.websocket("/api/ws")
async def ws_feed(websocket: WebSocket):
    """Push live snapshots. The client may send `{"type":"filter","status":...}`
    to scope the job list; everything else is pushed automatically on change."""
    await hub.connect(websocket)
    try:
        await hub.send_snapshot(websocket)  # immediate first paint
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "filter":
                hub.set_filter(websocket, msg.get("status"))
                await hub.send_snapshot(websocket)  # reflect the new filter now
    except WebSocketDisconnect:
        hub.disconnect(websocket)
    except Exception:  # noqa: BLE001 — any transport error closes the socket
        hub.disconnect(websocket)


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #

@app.post("/api/jobs", status_code=201)
def create_job(req: EnqueueRequest):
    if req.task not in tasks.registry():
        raise HTTPException(400, f"unknown task '{req.task}'. See GET /api/tasks")
    job = q.enqueue(
        task=req.task,
        payload=req.payload,
        queue=req.queue,
        priority=req.priority,
        max_attempts=req.max_attempts,
        delay_seconds=req.delay_seconds,
        idempotency_key=req.idempotency_key,
    )
    hub.notify()
    return job


@app.get("/api/jobs")
def get_jobs(
    status: Optional[str] = None,
    queue: Optional[str] = None,
    task: Optional[str] = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    return {"jobs": q.list_jobs(status=status, queue=queue, task=task, limit=limit, offset=offset)}


@app.get("/api/jobs/{job_id}")
def get_one(job_id: str):
    job = q.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@app.post("/api/jobs/{job_id}/retry")
def retry(job_id: str):
    job = q.retry_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    hub.notify()
    return job


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete(job_id: str):
    if not q.delete_job(job_id):
        raise HTTPException(404, "job not found")
    hub.notify()


@app.post("/api/jobs/purge")
def purge(status: Optional[str] = None):
    deleted = q.purge(status)
    hub.notify()
    return {"deleted": deleted}


# --------------------------------------------------------------------------- #
# Monitoring
# --------------------------------------------------------------------------- #

@app.get("/api/stats")
def get_stats():
    return q.stats()


@app.get("/api/tasks")
def get_tasks():
    return {"tasks": tasks.registry()}


@app.get("/api/queues")
def get_queues():
    return {"queues": _queues_list()}


@app.put("/api/queues/{name}")
def set_queue_limit(name: str, req: QueueLimitRequest):
    pool.set_limit(name, req.concurrency)
    hub.notify()
    return {"name": name, "concurrency": pool.get_limit(name)}


# --------------------------------------------------------------------------- #
# Worker control
# --------------------------------------------------------------------------- #

@app.get("/api/workers")
def workers_status():
    return pool.status()


@app.post("/api/workers/pause")
def pause():
    pool.pause()
    hub.notify()
    return pool.status()


@app.post("/api/workers/resume")
def resume():
    pool.resume()
    hub.notify()
    return pool.status()


# --------------------------------------------------------------------------- #
# Demo helpers
# --------------------------------------------------------------------------- #

@app.post("/api/seed")
def seed(req: SeedRequest):
    """Enqueue a realistic mix of jobs so the dashboard has something to show."""
    plans = [
        ("echo", "default", {}, 3),
        ("sleep", "default", {"seconds": lambda: round(random.uniform(1, 5), 1)}, 3),
        ("compute", "reports", {"n": lambda: random.choice([500_000, 1_000_000, 2_000_000])}, 2),
        ("flaky", "default", {"fail_times": lambda: random.choice([1, 2, 3])}, 4),
        ("always_fail", "emails", {}, 2),
        ("send_email", "emails", {"to": "team@example.com", "bounce": True}, 3),
    ]
    created = 0
    for _ in range(req.count):
        task, queue, tmpl, max_attempts = random.choice(plans)
        payload = {k: (v() if callable(v) else v) for k, v in tmpl.items()}
        q.enqueue(
            task=task,
            payload=payload,
            queue=queue,
            priority=random.choice([0, 0, 0, 1, 2]),
            max_attempts=max_attempts,
            delay_seconds=random.choice([0, 0, 0, 2, 5]),
        )
        created += 1
    hub.notify()
    return {"created": created}


@app.post("/api/admin/reset")
def reset():
    db.reset_db()
    hub.notify()
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"status": "ok", "workers": pool.status()}
