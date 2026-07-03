import { useState } from "react";
import { api } from "../api";
import type { QueueInfo } from "../types";

const SEG: { key: string; color: string }[] = [
  { key: "active", color: "var(--active)" },
  { key: "queued", color: "var(--queued)" },
  { key: "retrying", color: "var(--retrying)" },
  { key: "completed", color: "var(--completed)" },
  { key: "dead", color: "var(--dead)" },
];

export function QueuesPanel({
  queues,
  onError,
}: {
  queues: QueueInfo[];
  onError: (m: string) => void;
}) {
  return (
    <div className="panel">
      <h2>Queues · concurrency limits</h2>
      {queues.length === 0 && <div className="empty">No queues yet</div>}
      {queues.map((q) => (
        <QueueRow key={q.name} q={q} onError={onError} />
      ))}
    </div>
  );
}

function QueueRow({ q, onError }: { q: QueueInfo; onError: (m: string) => void }) {
  const [conc, setConc] = useState(q.concurrency);
  const total = Object.values(q.counts).reduce((a, b) => a + (b ?? 0), 0) || 1;

  const commit = async (val: number) => {
    try {
      await api.setConcurrency(q.name, val);
    } catch (e) {
      onError((e as Error).message);
    }
  };

  return (
    <div className="queue-row">
      <span className="queue-name">{q.name}</span>
      <div className="queue-bar" title={JSON.stringify(q.counts)}>
        {SEG.map((s) => {
          const v = q.counts[s.key as keyof typeof q.counts] ?? 0;
          return v ? (
            <span key={s.key} style={{ width: `${(v / total) * 100}%`, background: s.color }} />
          ) : null;
        })}
      </div>
      <span className="dim mono" style={{ minWidth: 66, textAlign: "right" }}>
        {q.counts.active ?? 0}/{conc} busy
      </span>
      <input
        className="conc-input mono"
        type="number"
        min={0}
        value={conc}
        onChange={(e) => setConc(+e.target.value)}
        onBlur={() => commit(conc)}
        onKeyDown={(e) => e.key === "Enter" && commit(conc)}
        title="Max concurrent jobs for this queue"
      />
    </div>
  );
}
