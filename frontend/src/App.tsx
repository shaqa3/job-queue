import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Job, TaskInfo } from "./types";
import { useLive } from "./useLive";
import { Metrics, StatCards } from "./components/StatCards";
import { ThroughputChart } from "./components/ThroughputChart";
import { EnqueueForm } from "./components/EnqueueForm";
import { QueuesPanel } from "./components/QueuesPanel";
import { JobsTable } from "./components/JobsTable";
import { JobDrawer } from "./components/JobDrawer";
import { Controls } from "./components/Controls";

export default function App() {
  const [filter, setFilter] = useState("");
  const { stats, jobs, queues, workers, connected, transport } = useLive(filter);

  const [tasks, setTasks] = useState<Record<string, TaskInfo>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; err?: boolean } | null>(null);

  const flash = useCallback((msg: string, err = false) => {
    setToast({ msg, err });
    setTimeout(() => setToast(null), 2600);
  }, []);

  // Load the task registry once.
  useEffect(() => {
    api.tasks().then(setTasks).catch(() => {});
  }, []);

  // The live feed pushes updates automatically, so actions don't poll — they
  // just fire and the next snapshot reflects the change.
  const selected: Job | null =
    selectedId != null ? jobs.find((j) => j.id === selectedId) ?? null : null;

  const paused = workers?.paused ?? false;

  return (
    <div className="app">
      <header className="top">
        <div>
          <h1>Job Queue · Monitoring</h1>
          <div className="subtitle">
            {workers
              ? `${workers.num_workers} workers · ${workers.inflight} in-flight · up ${Math.round(
                  workers.uptime_seconds
                )}s`
              : "connecting…"}
          </div>
        </div>
        <div className="spacer" />
        <span className="live" title={connected ? `live via ${transport}` : "reconnecting"}>
          <span className={`dot ${!connected ? "paused" : paused ? "paused" : "pulse"}`} />
          {!connected
            ? "disconnected"
            : paused
            ? "paused"
            : transport === "ws"
            ? "live · ws"
            : "live · poll"}
        </span>
      </header>

      <div style={{ marginBottom: 16 }}>
        <Controls workers={workers} onAction={(m) => flash(m)} onError={(m) => flash(m, true)} />
      </div>

      <StatCards stats={stats} />

      <div className="grid cols-2" style={{ marginBottom: 16 }}>
        <ThroughputChart stats={stats} />
        <div className="panel">
          <h2>At a glance</h2>
          <Metrics stats={stats} />
          <div style={{ height: 12 }} />
          <div className="hint">
            Delivery is <strong>at-least-once</strong>: jobs are claimed before running, so a
            crashed worker's job is recovered and retried. Use idempotency keys for exactly-once
            effects.
          </div>
        </div>
      </div>

      <div className="grid cols-2" style={{ marginBottom: 16 }}>
        <EnqueueForm
          tasks={tasks}
          onEnqueued={(m) => flash(m)}
          onError={(m) => flash(m, true)}
        />
        <QueuesPanel queues={queues} onError={(m) => flash(m, true)} />
      </div>

      <JobsTable
        jobs={jobs}
        stats={stats}
        filter={filter}
        onFilter={setFilter}
        onSelect={(j) => setSelectedId(j.id)}
      />

      {selected && (
        <JobDrawer
          job={selected}
          onClose={() => setSelectedId(null)}
          onChanged={(m) => flash(m)}
          onError={(m) => flash(m, true)}
        />
      )}

      {toast && <div className={`toast ${toast.err ? "err" : ""}`}>{toast.msg}</div>}
    </div>
  );
}
