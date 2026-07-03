"""In-process worker pool.

A fixed set of daemon threads poll the queue for due jobs and run them. Design
points worth calling out for the portfolio write-up:

* **Concurrency limits per queue** — enforced at claim time (see queue.claim_next),
  so a burst on one queue can't starve the others.
* **Graceful shutdown** — `shutdown()` stops new claims and waits (drains) for
  in-flight jobs to finish before returning; anything still `active` at process
  exit is recovered on next startup by `requeue_stuck_active`.
* **Pause/resume** — flips a flag so the dashboard can halt processing without
  tearing down threads.
"""

import threading
import time
import traceback
from typing import Callable, Dict, List, Optional

from . import queue as q
from .tasks import JobContext, TaskError, run


class WorkerPool:
    def __init__(
        self,
        num_workers: int = 4,
        poll_interval: float = 0.25,
        default_concurrency: int = 5,
        queue_limits: Optional[Dict[str, int]] = None,
        backoff_base: float = 2.0,
        backoff_cap: float = 60.0,
        on_change: Optional[Callable[[], None]] = None,
    ):
        self.num_workers = num_workers
        self.poll_interval = poll_interval
        self.default_concurrency = default_concurrency
        self.queue_limits: Dict[str, int] = dict(queue_limits or {})
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        # Fired (thread-safe) whenever a job changes state, so the WebSocket hub
        # can push an update. No-op if unset.
        self.on_change: Optional[Callable[[], None]] = on_change

        self._threads: List[threading.Thread] = []
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._inflight: Dict[str, str] = {}  # worker_id -> job_id
        self._lock = threading.Lock()
        self.started_at: Optional[float] = None

    # -- config -------------------------------------------------------------- #
    def get_limit(self, queue_name: str) -> int:
        return self.queue_limits.get(queue_name, self.default_concurrency)

    def set_limit(self, queue_name: str, limit: int) -> None:
        self.queue_limits[queue_name] = max(0, int(limit))

    # -- lifecycle ----------------------------------------------------------- #
    def start(self) -> None:
        # Recover jobs left 'active' by a previous (crashed) run.
        recovered = q.requeue_stuck_active()
        if recovered:
            print(f"[worker] recovered {recovered} interrupted job(s)")
        self.started_at = time.time()
        for i in range(self.num_workers):
            t = threading.Thread(target=self._loop, args=(f"w{i}",), daemon=True, name=f"worker-{i}")
            t.start()
            self._threads.append(t)
        print(f"[worker] started {self.num_workers} worker(s)")

    def shutdown(self, drain_timeout: float = 30.0) -> None:
        """Stop claiming and wait for in-flight jobs to drain."""
        print("[worker] shutdown requested — draining in-flight jobs...")
        self._stop.set()
        deadline = time.time() + drain_timeout
        for t in self._threads:
            remaining = max(0.0, deadline - time.time())
            t.join(timeout=remaining)
        still = self.inflight_count()
        print(f"[worker] stopped ({still} job(s) still in flight will be recovered on restart)")

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    # -- introspection ------------------------------------------------------- #
    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def inflight_count(self) -> int:
        with self._lock:
            return len(self._inflight)

    def status(self) -> dict:
        return {
            "num_workers": self.num_workers,
            "paused": self.paused,
            "inflight": self.inflight_count(),
            "default_concurrency": self.default_concurrency,
            "queue_limits": self.queue_limits,
            "backoff_base": self.backoff_base,
            "backoff_cap": self.backoff_cap,
            "uptime_seconds": round(time.time() - self.started_at, 1) if self.started_at else 0,
        }

    # -- the loop ------------------------------------------------------------ #
    def _loop(self, worker_id: str) -> None:
        while not self._stop.is_set():
            if self._paused.is_set():
                time.sleep(self.poll_interval)
                continue

            job = q.claim_next(worker_id, self.get_limit)
            if job is None:
                time.sleep(self.poll_interval)
                continue

            self._process(worker_id, job)

    def _emit(self) -> None:
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001 — notification must never break the worker
                pass

    def _process(self, worker_id: str, job: dict) -> None:
        job_id = job["id"]
        with self._lock:
            self._inflight[worker_id] = job_id
        self._emit()  # job just transitioned queued -> active
        try:
            ctx = JobContext(
                job_id=job_id,
                queue=job["queue"],
                attempt=job["attempts"],
                max_attempts=job["max_attempts"],
            )
            result = run(job["task"], job["payload"], ctx)
            q.complete_job(job_id, result)
        except Exception as exc:  # noqa: BLE001 — any handler error is a failed attempt
            err = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, TaskError):
                # Expected, handler-signalled failure — log concisely.
                print(f"[worker] job {job_id[:8]} {job['task']} failed: {err}")
            else:
                # Unexpected error — keep the full traceback for debugging.
                traceback.print_exc()
            q.fail_job(job_id, err, self.backoff_base, self.backoff_cap)
        finally:
            with self._lock:
                self._inflight.pop(worker_id, None)
            self._emit()  # job reached a terminal/retrying state
