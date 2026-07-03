import { api } from "../api";
import type { WorkersStatus } from "../types";

export function Controls({
  workers,
  onAction,
  onError,
}: {
  workers: WorkersStatus | null;
  onAction: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const wrap = (fn: () => Promise<unknown>, msg: string) => async () => {
    try {
      await fn();
      onAction(msg);
    } catch (e) {
      onError((e as Error).message);
    }
  };

  const paused = workers?.paused ?? false;

  return (
    <div className="controls">
      <button className="primary" onClick={wrap(() => api.seed(25), "Seeded 25 demo jobs")}>
        + Seed demo jobs
      </button>
      {paused ? (
        <button onClick={wrap(() => api.resume(), "Workers resumed")}>▶ Resume workers</button>
      ) : (
        <button onClick={wrap(() => api.pause(), "Workers paused")}>⏸ Pause workers</button>
      )}
      <button onClick={wrap(() => api.purge("completed"), "Cleared completed jobs")}>
        Clear completed
      </button>
      <button className="danger" onClick={wrap(() => api.reset(), "All jobs cleared")}>
        Reset
      </button>
    </div>
  );
}
