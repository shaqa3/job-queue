import type { Stats } from "../types";

// Simple stacked-bar throughput chart drawn as inline SVG (no chart lib).
export function ThroughputChart({ stats }: { stats: Stats | null }) {
  const series = stats?.series ?? [];
  const W = 640;
  const H = 120;
  const pad = 4;
  const n = Math.max(series.length, 1);
  const barW = (W - pad * 2) / n;
  const max = Math.max(1, ...series.map((s) => s.completed + s.failed));

  return (
    <div className="panel">
      <h2>Throughput · last {(stats?.series.length ?? 0) * (stats?.bucket_seconds ?? 5)}s</h2>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        {series.map((s, i) => {
          const x = pad + i * barW;
          const cH = (s.completed / max) * (H - 8);
          const fH = (s.failed / max) * (H - 8);
          const gap = barW > 3 ? 1 : 0;
          return (
            <g key={i}>
              <rect
                x={x + gap}
                y={H - cH - fH}
                width={barW - gap * 2}
                height={cH}
                fill="var(--completed)"
                rx={1}
              />
              <rect
                x={x + gap}
                y={H - fH}
                width={barW - gap * 2}
                height={fH}
                fill="var(--dead)"
                rx={1}
              />
            </g>
          );
        })}
        <line x1={0} y1={H - 0.5} x2={W} y2={H - 0.5} stroke="var(--border)" strokeWidth={1} />
      </svg>
      <div className="chart-legend">
        <span><i className="swatch" style={{ background: "var(--completed)" }} /> Completed</span>
        <span><i className="swatch" style={{ background: "var(--dead)" }} /> Failed</span>
        <span className="dim" style={{ marginLeft: "auto" }}>
          {stats?.throughput_per_min.toFixed(1) ?? "—"} completed/min
        </span>
      </div>
    </div>
  );
}
