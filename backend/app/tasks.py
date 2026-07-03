"""Task registry and demo task handlers.

A "task" is just a named Python callable. Handlers receive the decoded payload
and a JobContext (so they can behave differently per attempt, which is handy for
demonstrating retries). Whatever a handler returns is stored as the job result;
raising an exception marks the attempt as failed.
"""

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict


@dataclass
class JobContext:
    job_id: str
    queue: str
    attempt: int          # 1-based: which attempt is running right now
    max_attempts: int


class TaskError(Exception):
    """Raised by handlers to signal a (possibly retryable) failure."""


Handler = Callable[[Dict[str, Any], JobContext], Any]

_REGISTRY: Dict[str, Dict[str, Any]] = {}


def task(name: str, description: str = "") -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        _REGISTRY[name] = {"fn": fn, "description": description}
        return fn
    return decorator


def registry() -> Dict[str, Dict[str, Any]]:
    return {name: {"description": meta["description"]} for name, meta in _REGISTRY.items()}


def run(task_name: str, payload: Dict[str, Any], ctx: JobContext) -> Any:
    meta = _REGISTRY.get(task_name)
    if meta is None:
        raise TaskError(f"unknown task '{task_name}'")
    return meta["fn"](payload or {}, ctx)


# --------------------------------------------------------------------------- #
# Demo tasks — enough variety to exercise every part of the UI.
# --------------------------------------------------------------------------- #

@task("echo", "Return the payload unchanged. Instant success.")
def _echo(payload: Dict[str, Any], ctx: JobContext) -> Any:
    return {"echoed": payload}


@task("sleep", "Sleep for payload.seconds (default 2). Shows 'active' state.")
def _sleep(payload: Dict[str, Any], ctx: JobContext) -> Any:
    seconds = float(payload.get("seconds", 2))
    time.sleep(min(seconds, 60))
    return {"slept": seconds}


@task("compute", "CPU work: sum of squares up to payload.n. Returns the total.")
def _compute(payload: Dict[str, Any], ctx: JobContext) -> Any:
    n = int(payload.get("n", 1_000_000))
    total = sum(i * i for i in range(n))
    return {"n": n, "sum_of_squares": total}


@task("flaky", "Fails the first payload.fail_times attempts, then succeeds. Demos backoff + retries.")
def _flaky(payload: Dict[str, Any], ctx: JobContext) -> Any:
    fail_times = int(payload.get("fail_times", 2))
    time.sleep(float(payload.get("seconds", 0.5)))
    if ctx.attempt <= fail_times:
        raise TaskError(f"transient failure on attempt {ctx.attempt} (will succeed after {fail_times})")
    return {"succeeded_on_attempt": ctx.attempt}


@task("always_fail", "Always raises. Exhausts retries and lands in the dead-letter queue.")
def _always_fail(payload: Dict[str, Any], ctx: JobContext) -> Any:
    time.sleep(float(payload.get("seconds", 0.3)))
    raise TaskError(payload.get("message", "permanent failure — this job will end up in the DLQ"))


@task("send_email", "Simulated I/O work with a small random-ish failure surface.")
def _send_email(payload: Dict[str, Any], ctx: JobContext) -> Any:
    to = payload.get("to", "user@example.com")
    time.sleep(float(payload.get("seconds", 1.0)))
    # Deterministic 'flake' driven by job id + attempt so retries can recover.
    if payload.get("bounce") and ctx.attempt == 1:
        raise TaskError(f"SMTP soft-bounce delivering to {to}")
    return {"delivered_to": to, "attempt": ctx.attempt}
