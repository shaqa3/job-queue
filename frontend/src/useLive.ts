import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Job, QueueInfo, Stats, WorkersStatus } from "./types";

export interface LiveData {
  stats: Stats | null;
  jobs: Job[];
  queues: QueueInfo[];
  workers: WorkersStatus | null;
  connected: boolean;
  /** "ws" when the live socket is driving updates, "poll" on fallback. */
  transport: "ws" | "poll";
}

interface Snapshot {
  type: "snapshot";
  stats: Stats;
  jobs: Job[];
  queues: QueueInfo[];
  workers: WorkersStatus;
}

const POLL_MS = 1000;

/**
 * Live dashboard data over a WebSocket (`/api/ws`), with automatic reconnect.
 * If the socket can't be established, we fall back to REST polling so the UI
 * keeps working. `filter` is forwarded to the server to scope the job list.
 */
export function useLive(filter: string): LiveData {
  const [data, setData] = useState<Omit<LiveData, "connected" | "transport">>({
    stats: null,
    jobs: [],
    queues: [],
    workers: null,
  });
  const [connected, setConnected] = useState(false);
  const [transport, setTransport] = useState<"ws" | "poll">("ws");

  const wsRef = useRef<WebSocket | null>(null);
  const filterRef = useRef(filter);
  filterRef.current = filter;

  useEffect(() => {
    let closed = false;
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let failures = 0;

    const stopPolling = () => {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    };

    const pollOnce = async () => {
      try {
        const params: Record<string, string | number> = { limit: 100 };
        if (filterRef.current) params.status = filterRef.current;
        const [stats, jobs, queues, workers] = await Promise.all([
          api.stats(),
          api.jobs(params),
          api.queues(),
          api.workers(),
        ]);
        setData({ stats, jobs, queues, workers });
        setConnected(true);
      } catch {
        setConnected(false);
      }
    };

    const startPolling = () => {
      if (pollTimer) return;
      setTransport("poll");
      pollOnce();
      pollTimer = setInterval(pollOnce, POLL_MS);
    };

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/api/ws`);
      wsRef.current = ws;

      ws.onopen = () => {
        failures = 0;
        stopPolling();
        setTransport("ws");
        setConnected(true);
        ws.send(JSON.stringify({ type: "filter", status: filterRef.current || null }));
      };

      ws.onmessage = (ev) => {
        const msg: Snapshot = JSON.parse(ev.data);
        if (msg.type === "snapshot") {
          setData({
            stats: msg.stats,
            jobs: msg.jobs,
            queues: msg.queues,
            workers: msg.workers,
          });
        }
      };

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        if (closed) return;
        failures += 1;
        // After a couple of failed attempts, fall back to polling while we
        // keep retrying the socket in the background.
        if (failures >= 2) startPolling();
        reconnectTimer = setTimeout(connect, Math.min(1000 * failures, 5000));
      };

      ws.onerror = () => ws.close();
    };

    connect();

    return () => {
      closed = true;
      clearTimeout(reconnectTimer);
      stopPolling();
      wsRef.current?.close();
    };
  }, []);

  // Forward filter changes to the server (or let the next poll pick them up).
  useEffect(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "filter", status: filter || null }));
    }
  }, [filter]);

  return { ...data, connected, transport };
}
