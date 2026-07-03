import type {
  Job,
  QueueInfo,
  Stats,
  TaskInfo,
  WorkersStatus,
} from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export interface EnqueuePayload {
  task: string;
  payload: Record<string, unknown>;
  queue: string;
  priority: number;
  max_attempts: number;
  delay_seconds: number;
  idempotency_key?: string;
}

export const api = {
  stats: () => req<Stats>("/stats"),
  workers: () => req<WorkersStatus>("/workers"),
  queues: () => req<{ queues: QueueInfo[] }>("/queues").then((r) => r.queues),
  tasks: () =>
    req<{ tasks: Record<string, TaskInfo> }>("/tasks").then((r) => r.tasks),
  jobs: (params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).map(([k, v]) => [k, String(v)])
    ).toString();
    return req<{ jobs: Job[] }>(`/jobs${qs ? `?${qs}` : ""}`).then((r) => r.jobs);
  },
  enqueue: (body: EnqueuePayload) =>
    req<Job>("/jobs", { method: "POST", body: JSON.stringify(body) }),
  retry: (id: string) => req<Job>(`/jobs/${id}/retry`, { method: "POST" }),
  remove: (id: string) => req<void>(`/jobs/${id}`, { method: "DELETE" }),
  purge: (status?: string) =>
    req<{ deleted: number }>(`/jobs/purge${status ? `?status=${status}` : ""}`, {
      method: "POST",
    }),
  pause: () => req<WorkersStatus>("/workers/pause", { method: "POST" }),
  resume: () => req<WorkersStatus>("/workers/resume", { method: "POST" }),
  setConcurrency: (name: string, concurrency: number) =>
    req<QueueInfo>(`/queues/${name}`, {
      method: "PUT",
      body: JSON.stringify({ concurrency }),
    }),
  seed: (count: number) =>
    req<{ created: number }>("/seed", {
      method: "POST",
      body: JSON.stringify({ count }),
    }),
  reset: () => req<{ ok: boolean }>("/admin/reset", { method: "POST" }),
};
