export type JobStatus =
  | "queued"
  | "active"
  | "retrying"
  | "completed"
  | "dead";

export interface Job {
  id: string;
  queue: string;
  task: string;
  payload: Record<string, unknown>;
  priority: number;
  status: JobStatus;
  attempts: number;
  max_attempts: number;
  available_at: number;
  created_at: number;
  updated_at: number;
  started_at: number | null;
  finished_at: number | null;
  runtime_ms: number | null;
  result: unknown;
  error: string | null;
  idempotency_key: string | null;
  worker_id: string | null;
  delayed: boolean;
}

export interface StatsSeriesPoint {
  t: number;
  completed: number;
  failed: number;
}

export interface Stats {
  counts: Record<JobStatus, number>;
  scheduled: number;
  total: number;
  success_rate: number | null;
  avg_runtime_ms: number | null;
  throughput_per_min: number;
  series: StatsSeriesPoint[];
  bucket_seconds: number;
  now: number;
}

export interface QueueInfo {
  name: string;
  concurrency: number;
  counts: Partial<Record<JobStatus, number>>;
}

export interface WorkersStatus {
  num_workers: number;
  paused: boolean;
  inflight: number;
  default_concurrency: number;
  queue_limits: Record<string, number>;
  backoff_base: number;
  backoff_cap: number;
  uptime_seconds: number;
}

export interface TaskInfo {
  description: string;
}
