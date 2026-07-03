import type { Job, JobStatus, Stats } from "../types";

const FILTERS: { key: string; label: string }[] = [
  { key: "", label: "All" },
  { key: "queued", label: "Queued" },
  { key: "active", label: "Active" },
  { key: "retrying", label: "Retrying" },
  { key: "completed", label: "Completed" },
  { key: "dead", label: "Dead (DLQ)" },
];

function ago(ts: number | null): string {
  if (!ts) return "—";
  const s = Date.now() / 1000 - ts;
  if (s < 0) return `in ${Math.abs(Math.round(s))}s`;
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

export function JobsTable({
  jobs,
  stats,
  filter,
  onFilter,
  onSelect,
}: {
  jobs: Job[];
  stats: Stats | null;
  filter: string;
  onFilter: (f: string) => void;
  onSelect: (job: Job) => void;
}) {
  const countFor = (key: string): number | null => {
    if (!stats) return null;
    if (key === "") return stats.total;
    return stats.counts[key as JobStatus] ?? 0;
  };

  return (
    <div className="panel">
      <h2>Jobs</h2>
      <div className="tabs">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            className={`tab ${filter === f.key ? "active" : ""}`}
            onClick={() => onFilter(f.key)}
          >
            {f.label}
            <span className="count">{countFor(f.key)}</span>
          </button>
        ))}
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Task</th>
              <th>Queue</th>
              <th>Status</th>
              <th>Prio</th>
              <th>Attempts</th>
              <th>Runtime</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id} className="row" onClick={() => onSelect(j)}>
                <td className="mono dim">{j.id.slice(0, 8)}</td>
                <td>{j.task}</td>
                <td className="dim">{j.queue}</td>
                <td>
                  <span className={`badge ${j.delayed ? "scheduled" : j.status}`}>
                    {j.delayed ? "scheduled" : j.status}
                  </span>
                </td>
                <td className="dim">{j.priority}</td>
                <td>
                  <span className="attempts-pill mono">
                    {j.attempts}/{j.max_attempts}
                  </span>
                </td>
                <td className="dim mono">
                  {j.runtime_ms != null ? `${Math.round(j.runtime_ms)}ms` : "—"}
                </td>
                <td className="dim">{ago(j.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {jobs.length === 0 && <div className="empty">No jobs match this filter</div>}
      </div>
    </div>
  );
}
