import type { Stats } from "../types";

const CARDS: { key: keyof Stats["counts"] | "scheduled"; label: string; cls: string }[] = [
  { key: "queued", label: "Queued", cls: "queued" },
  { key: "scheduled", label: "Scheduled", cls: "scheduled" },
  { key: "active", label: "Active", cls: "active" },
  { key: "retrying", label: "Retrying", cls: "retrying" },
  { key: "completed", label: "Completed", cls: "completed" },
  { key: "dead", label: "Dead (DLQ)", cls: "dead" },
];

export function StatCards({ stats }: { stats: Stats | null }) {
  const value = (key: string): number =>
    key === "scheduled"
      ? stats?.scheduled ?? 0
      : (stats?.counts as Record<string, number> | undefined)?.[key] ?? 0;

  return (
    <div className="stats">
      {CARDS.map((c) => (
        <div key={c.key} className={`stat ${c.cls}`}>
          <div className="num">{value(c.key)}</div>
          <div className="name">{c.label}</div>
        </div>
      ))}
    </div>
  );
}

export function Metrics({ stats }: { stats: Stats | null }) {
  const rate =
    stats?.success_rate == null ? "—" : `${Math.round(stats.success_rate * 100)}%`;
  const avg =
    stats?.avg_runtime_ms == null ? "—" : `${Math.round(stats.avg_runtime_ms)} ms`;
  const thr = stats ? stats.throughput_per_min.toFixed(1) : "—";
  return (
    <div className="metrics">
      <div className="metric">
        <div className="num">{thr}</div>
        <div className="name">Completed / min</div>
      </div>
      <div className="metric">
        <div className="num">{rate}</div>
        <div className="name">Success rate</div>
      </div>
      <div className="metric">
        <div className="num">{avg}</div>
        <div className="name">Avg runtime</div>
      </div>
      <div className="metric">
        <div className="num">{stats?.total ?? "—"}</div>
        <div className="name">Total jobs</div>
      </div>
    </div>
  );
}
