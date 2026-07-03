import { useMemo, useState } from "react";
import { api, type EnqueuePayload } from "../api";
import type { TaskInfo } from "../types";

// Sensible starter payloads per demo task.
const PRESETS: Record<string, string> = {
  echo: '{ "hello": "world" }',
  sleep: '{ "seconds": 3 }',
  compute: '{ "n": 1000000 }',
  flaky: '{ "fail_times": 2 }',
  always_fail: '{ "message": "boom" }',
  send_email: '{ "to": "team@example.com", "bounce": true }',
};

export function EnqueueForm({
  tasks,
  onEnqueued,
  onError,
}: {
  tasks: Record<string, TaskInfo>;
  onEnqueued: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const taskNames = useMemo(() => Object.keys(tasks), [tasks]);
  const [task, setTask] = useState("flaky");
  const [queue, setQueue] = useState("default");
  const [priority, setPriority] = useState(0);
  const [maxAttempts, setMaxAttempts] = useState(3);
  const [delay, setDelay] = useState(0);
  const [payload, setPayload] = useState(PRESETS.flaky);
  const [busy, setBusy] = useState(false);

  const pickTask = (t: string) => {
    setTask(t);
    setPayload(PRESETS[t] ?? "{}");
  };

  const submit = async () => {
    let parsed: Record<string, unknown>;
    try {
      parsed = payload.trim() ? JSON.parse(payload) : {};
    } catch {
      onError("Payload is not valid JSON");
      return;
    }
    const body: EnqueuePayload = {
      task,
      payload: parsed,
      queue: queue.trim() || "default",
      priority,
      max_attempts: maxAttempts,
      delay_seconds: delay,
    };
    setBusy(true);
    try {
      await api.enqueue(body);
      onEnqueued(`Enqueued ${task} on "${body.queue}"`);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h2>Enqueue a job</h2>
      <div className="form-row">
        <div>
          <label>Task</label>
          <select value={task} onChange={(e) => pickTask(e.target.value)}>
            {taskNames.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <div className="hint">{tasks[task]?.description}</div>
        </div>
        <div>
          <label>Queue</label>
          <input value={queue} onChange={(e) => setQueue(e.target.value)} placeholder="default" />
        </div>
      </div>

      <div className="form-row">
        <div>
          <label>Priority (higher runs first)</label>
          <input type="number" value={priority} onChange={(e) => setPriority(+e.target.value)} />
        </div>
        <div>
          <label>Max attempts</label>
          <input type="number" min={1} max={25} value={maxAttempts}
            onChange={(e) => setMaxAttempts(+e.target.value)} />
        </div>
      </div>

      <div className="field">
        <label>Delay (seconds) — schedule for later</label>
        <input type="number" min={0} value={delay} onChange={(e) => setDelay(+e.target.value)} />
      </div>

      <div className="field">
        <label>Payload (JSON)</label>
        <textarea rows={4} value={payload} onChange={(e) => setPayload(e.target.value)} />
      </div>

      <button className="primary" onClick={submit} disabled={busy} style={{ width: "100%" }}>
        {busy ? "Enqueuing…" : "Enqueue job"}
      </button>
    </div>
  );
}
