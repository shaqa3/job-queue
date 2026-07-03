import { api } from "../api";
import type { Job } from "../types";

function fmt(ts: number | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

export function JobDrawer({
  job,
  onClose,
  onChanged,
  onError,
}: {
  job: Job;
  onClose: () => void;
  onChanged: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const act = async (fn: () => Promise<unknown>, msg: string) => {
    try {
      await fn();
      onChanged(msg);
      onClose();
    } catch (e) {
      onError((e as Error).message);
    }
  };

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", alignItems: "start" }}>
          <div>
            <h3>{job.task}</h3>
            <div className="dim mono">{job.id}</div>
          </div>
          <div className="spacer" />
          <button className="close-x" onClick={onClose}>×</button>
        </div>

        <div style={{ marginTop: 10 }}>
          <span className={`badge ${job.delayed ? "scheduled" : job.status}`}>
            {job.delayed ? "scheduled" : job.status}
          </span>
        </div>

        <div className="kv">
          <span className="k">Queue</span><span>{job.queue}</span>
          <span className="k">Priority</span><span>{job.priority}</span>
          <span className="k">Attempts</span><span>{job.attempts} / {job.max_attempts}</span>
          <span className="k">Runtime</span>
          <span>{job.runtime_ms != null ? `${Math.round(job.runtime_ms)} ms` : "—"}</span>
          <span className="k">Worker</span><span className="mono">{job.worker_id ?? "—"}</span>
          <span className="k">Created</span><span>{fmt(job.created_at)}</span>
          <span className="k">Available</span><span>{fmt(job.available_at)}</span>
          <span className="k">Started</span><span>{fmt(job.started_at)}</span>
          <span className="k">Finished</span><span>{fmt(job.finished_at)}</span>
          {job.idempotency_key && (
            <>
              <span className="k">Idem key</span>
              <span className="mono">{job.idempotency_key}</span>
            </>
          )}
        </div>

        <label>Payload</label>
        <pre className="code">{JSON.stringify(job.payload, null, 2)}</pre>

        {job.result != null && (
          <>
            <label style={{ marginTop: 12 }}>Result</label>
            <pre className="code">{JSON.stringify(job.result, null, 2)}</pre>
          </>
        )}

        {job.error && (
          <>
            <label style={{ marginTop: 12 }}>Error</label>
            <pre className="code error">{job.error}</pre>
          </>
        )}

        <div className="drawer-actions">
          <button
            className="primary"
            onClick={() => act(() => api.retry(job.id), "Job re-queued")}
          >
            {job.status === "dead" ? "Retry from DLQ" : "Re-run"}
          </button>
          <button
            className="danger"
            onClick={() => act(() => api.remove(job.id), "Job deleted")}
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}
