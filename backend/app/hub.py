"""WebSocket broadcast hub.

Workers run in plain threads, outside the asyncio event loop, so they can't touch
WebSocket connections directly. Instead they call `notify()` (thread-safe), which
flips an asyncio.Event via `loop.call_soon_threadsafe`. A single broadcaster task
living in the event loop wakes on that event — debounced so a burst of finishing
jobs coalesces into one push — computes a fresh snapshot, and fans it out to every
connected client. A periodic tick also fires so time-based changes (a scheduled
job coming due, the throughput window sliding) stay live even when nothing else
is happening.

Each client can set a `status` filter; the shared parts of the snapshot (stats,
queues, workers) are computed once per broadcast and only the per-client job list
is recomputed.
"""

import asyncio
import json
from typing import Any, Callable, Dict, Optional

from fastapi import WebSocket


class Hub:
    def __init__(self) -> None:
        self._clients: Dict[WebSocket, Dict[str, Any]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._dirty: Optional[asyncio.Event] = None
        self._build_common: Optional[Callable[[], Dict[str, Any]]] = None
        self._build_jobs: Optional[Callable[[Optional[str]], Any]] = None

    def bind(
        self,
        loop: asyncio.AbstractEventLoop,
        build_common: Callable[[], Dict[str, Any]],
        build_jobs: Callable[[Optional[str]], Any],
    ) -> None:
        self._loop = loop
        self._dirty = asyncio.Event()
        self._build_common = build_common
        self._build_jobs = build_jobs

    # -- connection registry ------------------------------------------------- #
    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients[ws] = {"status": None}

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.pop(ws, None)

    def set_filter(self, ws: WebSocket, status: Optional[str]) -> None:
        if ws in self._clients:
            self._clients[ws]["status"] = status or None

    @property
    def client_count(self) -> int:
        return len(self._clients)

    # -- notification (thread-safe) ------------------------------------------ #
    def notify(self) -> None:
        """Called from any thread (workers, request handlers) to request a push."""
        if self._loop is not None and self._dirty is not None:
            self._loop.call_soon_threadsafe(self._dirty.set)

    # -- sending ------------------------------------------------------------- #
    def _payload(self, ws: WebSocket, common: Dict[str, Any]) -> str:
        meta = self._clients.get(ws, {"status": None})
        return json.dumps(
            {"type": "snapshot", **common, "jobs": self._build_jobs(meta["status"])},
            default=str,
        )

    async def send_snapshot(self, ws: WebSocket) -> None:
        common = self._build_common()
        try:
            await ws.send_text(self._payload(ws, common))
        except Exception:  # noqa: BLE001 — client vanished mid-send
            self.disconnect(ws)

    async def broadcast(self) -> None:
        if not self._clients:
            return
        common = self._build_common()
        for ws in list(self._clients):
            try:
                await ws.send_text(self._payload(ws, common))
            except Exception:  # noqa: BLE001
                self.disconnect(ws)

    # -- broadcaster loop ---------------------------------------------------- #
    async def run(self, debounce: float = 0.12, tick: float = 1.0) -> None:
        assert self._dirty is not None, "call bind() before run()"
        while True:
            try:
                await asyncio.wait_for(self._dirty.wait(), timeout=tick)
            except asyncio.TimeoutError:
                pass  # periodic tick — refresh time-based state
            self._dirty.clear()
            await self.broadcast()
            await asyncio.sleep(debounce)  # coalesce bursts into one push
