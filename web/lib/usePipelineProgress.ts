import { useEffect, useRef, useState } from "react";

export type PipelineStatus = {
  running: boolean;
  phase: string | null;
  phases: string[];
  progress: { source: string; done: number; total: number } | null;
  sources: string[];
  jobs: Record<string, number>;
  last_error: string | null;
};

function formatDuration(seconds: number): string {
  if (seconds < 1) return "a few seconds";
  if (seconds < 60) return `${Math.ceil(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return s ? `${m}m ${s}s` : `${m}m`;
}

/** Whichever count is currently drivable as a progress bar: score jobs, or the
 * ingest source currently fetching. Null when the phase has nothing countable. */
function currentBar(status: PipelineStatus | null): { key: string; done: number; total: number } | null {
  if (!status) return null;
  if (status.phase === "score") {
    const jobs = status.jobs ?? {};
    const done = (jobs.completed ?? 0) + (jobs.failed ?? 0);
    const total = done + (jobs.pending ?? 0) + (jobs.processing ?? 0);
    return total ? { key: "score", done, total } : null;
  }
  if (status.phase === "ingest" && status.progress) {
    return { key: `ingest:${status.progress.source}`, done: status.progress.done, total: status.progress.total };
  }
  return null;
}

/** Tracks how a polled PipelineStatus changes over time: the elapsed/ETA clock,
 * the score/ingest progress bar, and the completion toast. Callers own fetching
 * `status` itself (e.g. by polling GET /pipeline/status) — this hook only
 * derives UI state from it. */
export function usePipelineProgress(status: PipelineStatus | null) {
  const [toast, setToast] = useState<{ completed: number; failed: number } | null>(null);
  const [, setTick] = useState(0); // forces a re-render each second so the elapsed/ETA clock ticks
  const runStartRef = useRef<number | null>(null);
  const phaseStartRef = useRef<Record<string, number>>({});
  // rate baseline for whichever count is currently driving a progress bar (score jobs,
  // or an ingest source's item count) — keyed so switching source/phase resets the rate
  const rateBaselineRef = useRef<{ key: string; time: number; done: number } | null>(null);
  const prevRunningRef = useRef(false);

  // tick the elapsed/ETA clock once a second while running
  useEffect(() => {
    if (!status?.running) return;
    const timer = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [status?.running]);

  // track phase timing for the ETA heuristic, and fire the completion toast
  useEffect(() => {
    if (!status) return;
    if (status.running) {
      if (runStartRef.current === null) runStartRef.current = Date.now();
      if (status.phase && phaseStartRef.current[status.phase] === undefined) {
        phaseStartRef.current[status.phase] = Date.now();
      }
      const bar = currentBar(status);
      if (bar && rateBaselineRef.current?.key !== bar.key) {
        rateBaselineRef.current = { key: bar.key, time: Date.now(), done: bar.done };
      }
    }
    if (prevRunningRef.current && !status.running) {
      const jobsNow = status.jobs ?? {};
      if (!status.last_error) setToast({ completed: jobsNow.completed ?? 0, failed: jobsNow.failed ?? 0 });
      runStartRef.current = null;
      phaseStartRef.current = {};
      rateBaselineRef.current = null;
    }
    prevRunningRef.current = status.running;
  }, [status]);

  // auto-dismiss the completion toast
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(timer);
  }, [toast]);

  const jobs = status?.jobs ?? {};
  const jobsLine = ["pending", "processing", "completed", "failed"]
    .filter((s) => jobs[s])
    .map((s) => `${jobs[s]} ${s}`)
    .join(" · ");

  const bar = currentBar(status);
  const barPct = bar?.total ? Math.round((bar.done / bar.total) * 100) : 0;

  const elapsedSec = runStartRef.current ? (Date.now() - runStartRef.current) / 1000 : 0;
  let etaLabel: string | null = null;
  if (bar && rateBaselineRef.current?.key === bar.key) {
    const { time, done } = rateBaselineRef.current;
    const sinceSec = (Date.now() - time) / 1000;
    const doneSince = bar.done - done;
    if (sinceSec > 2 && doneSince > 0 && bar.total > bar.done) {
      const rate = doneSince / sinceSec; // items/sec
      etaLabel = formatDuration((bar.total - bar.done) / rate);
    }
  }

  return {
    toast,
    dismissToast: () => setToast(null),
    bar,
    barPct,
    elapsedLabel: formatDuration(elapsedSec),
    etaLabel,
    jobsLine,
  };
}
