"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

type ShortlistItem = {
  score: number;
  summary: string;
  title: string;
  company: string | null;
  url: string;
  remote: boolean | null;
  location: string | null;
  posted_at: string | null;
};

type ShortlistPage = {
  items: ShortlistItem[];
  total: number;
};

type PipelineStatus = {
  running: boolean;
  phase: string | null;
  phases: string[];
  progress: { source: string; done: number; total: number } | null;
  sources: string[];
  jobs: Record<string, number>;
  last_error: string | null;
};

const PAGE_SIZE = 10;

const SOURCE_ORDER = ["eldorado", "boards", "gmail"];
const SOURCE_LABELS: Record<string, string> = {
  eldorado: "Eldorado",
  boards: "Boards.json",
  gmail: "Gmail alerts",
};

const PHASE_ORDER = ["ingest", "embed", "retrieve", "score", "done"];
const PHASE_LABELS: Record<string, string> = {
  ingest: "Ingest",
  embed: "Embed",
  retrieve: "Retrieve",
  score: "Score",
  done: "Done",
};

function formatDuration(seconds: number): string {
  if (seconds < 1) return "a few seconds";
  if (seconds < 60) return `${Math.ceil(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return s ? `${m}m ${s}s` : `${m}m`;
}

function PhaseStepper({ phases, current }: { phases: string[]; current: string | null }) {
  const currentIndex = current ? phases.indexOf(current) : -1;
  return (
    <div className="flex items-center">
      {phases.map((p, i) => {
        const state = current === "done" || i < currentIndex ? "done" : i === currentIndex ? "active" : "pending";
        return (
          <div key={p} className="flex items-center">
            <div className="flex flex-col items-center gap-1">
              <span
                className={
                  state === "done"
                    ? "flex h-5 w-5 items-center justify-center rounded-full bg-black text-[10px] text-white dark:bg-white dark:text-black"
                    : state === "active"
                      ? "flex h-5 w-5 items-center justify-center rounded-full border-2 border-black dark:border-white"
                      : "flex h-5 w-5 items-center justify-center rounded-full border border-gray-300 dark:border-gray-700"
                }
              >
                {state === "done" ? "✓" : ""}
              </span>
              <span
                className={`text-[11px] ${
                  state === "pending" ? "text-gray-400 dark:text-gray-600" : "text-gray-700 dark:text-gray-300"
                }`}
              >
                {PHASE_LABELS[p] ?? p}
              </span>
            </div>
            {i < phases.length - 1 && (
              <span
                className={`mx-1.5 mb-4 h-px w-8 shrink-0 ${
                  state === "done" ? "bg-black dark:bg-white" : "bg-gray-200 dark:bg-gray-800"
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

const SORTS = [
  { value: "score", label: "Best match" },
  { value: "newest", label: "Newest" },
  { value: "added", label: "Recently added" },
] as const;

const MODES = [
  { value: "", label: "Any" },
  { value: "true", label: "Remote" },
  { value: "false", label: "On-site" },
] as const;

function Chip({
  active,
  onClick,
  disabled,
  children,
}: {
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active}
      className={`rounded-full border px-3 py-1 text-sm transition-colors disabled:opacity-40 ${
        active
          ? "border-black bg-black text-white dark:border-white dark:bg-white dark:text-black"
          : "border-gray-300 text-gray-600 hover:border-gray-400 dark:border-gray-700 dark:text-gray-300"
      }`}
    >
      {children}
    </button>
  );
}

/** Looks like a checkbox, not a pill — unlike Chip, each one toggles independently
 * rather than the group being a single choice. Same interaction, different affordance
 * so it doesn't read as another Sort/Work-mode-style exclusive picker. */
function SourceToggle({
  active,
  onClick,
  disabled,
  children,
}: {
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active}
      className="flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1 text-sm text-gray-700 transition-colors disabled:opacity-40 dark:border-gray-700 dark:text-gray-300"
    >
      <span
        className={`flex h-3.5 w-3.5 items-center justify-center rounded-sm border text-[9px] leading-none ${
          active
            ? "border-black bg-black text-white dark:border-white dark:bg-white dark:text-black"
            : "border-gray-400 dark:border-gray-600"
        }`}
      >
        {active ? "✓" : ""}
      </span>
      {children}
    </button>
  );
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

function daysAgo(iso: string | null): string | null {
  if (!iso) return null;
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  return days === 1 ? "1d ago" : `${days}d ago`;
}

export default function Home() {
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [page, setPage] = useState<ShortlistPage>({ items: [], total: 0 });
  const [pageIndex, setPageIndex] = useState(0);
  const [sort, setSort] = useState<string>("score");
  const [remote, setRemote] = useState<string>("");
  const [hasResume, setHasResume] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sources, setSources] = useState<Set<string>>(new Set(SOURCE_ORDER));
  const [toast, setToast] = useState<{ completed: number; failed: number } | null>(null);
  const [, setTick] = useState(0); // forces a re-render each second so the elapsed/ETA clock ticks
  const runStartRef = useRef<number | null>(null);
  const phaseStartRef = useRef<Record<string, number>>({});
  // rate baseline for whichever count is currently driving a progress bar (score jobs,
  // or an ingest source's item count) — keyed so switching source/phase resets the rate
  const rateBaselineRef = useRef<{ key: string; time: number; done: number } | null>(null);
  const prevRunningRef = useRef(false);

  const refresh = useCallback(async () => {
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(pageIndex * PAGE_SIZE),
      sort,
    });
    if (remote) params.set("remote", remote);
    try {
      const [statusRes, listRes, resumeRes] = await Promise.all([
        fetch("/api/pipeline/status"),
        fetch(`/api/shortlist?${params}`),
        fetch("/api/profile/resume"),
      ]);
      setStatus(await statusRes.json());
      setPage(await listRes.json());
      setHasResume((await resumeRes.json()) !== null);
      setError(null);
    } catch {
      setError("Backend unreachable — is the FastAPI server running?");
    }
  }, [pageIndex, sort, remote]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // poll while a run is in progress
  useEffect(() => {
    if (!status?.running) return;
    const timer = setInterval(refresh, 1500);
    return () => clearInterval(timer);
  }, [status?.running, refresh]);

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

  function toggleSource(source: string) {
    setSources((prev) => {
      const next = new Set(prev);
      if (next.has(source)) next.delete(source);
      else next.add(source);
      return next;
    });
  }

  async function run() {
    setError(null);
    const res = await fetch("/api/pipeline/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      // no resume_text = use the CV stored in the profile; sources = [] just
      // re-retrieves/re-scores whatever is already ingested, no fetching at all
      body: JSON.stringify({ sources: [...sources] }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setError(typeof body.detail === "string" ? body.detail : "Request failed");
      return;
    }
    refresh();
  }

  async function stop() {
    setError(null);
    const res = await fetch("/api/pipeline/stop", { method: "POST" });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setError(typeof body.detail === "string" ? body.detail : "Request failed");
      return;
    }
    refresh();
  }

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

  const lastPage = Math.max(0, Math.ceil(page.total / PAGE_SIZE) - 1);
  const first = page.total === 0 ? 0 : pageIndex * PAGE_SIZE + 1;
  const last = Math.min(page.total, (pageIndex + 1) * PAGE_SIZE);

  return (
    <main className="mx-auto max-w-3xl px-6 py-12 font-sans">
      <div className="flex items-baseline justify-between gap-4">
        <h1 className="text-2xl font-bold">Job Search</h1>
        <Link href="/profile" className="text-sm text-gray-500 hover:underline dark:text-gray-400">
          Profile →
        </Link>
      </div>
      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
        Runs against the CV in your profile and scores what it finds.
      </p>

      <div className="mt-6 flex flex-wrap items-center gap-4">
        <button
          onClick={run}
          disabled={status?.running || hasResume !== true}
          className="rounded-lg bg-black px-5 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-white dark:text-black"
        >
          {status?.running ? "Running…" : "Find offers"}
        </button>
        {status?.running && (
          <button
            onClick={stop}
            className="rounded-lg border border-gray-300 px-5 py-2 text-sm font-medium text-gray-700 hover:border-gray-400 dark:border-gray-700 dark:text-gray-300"
          >
            Stop
          </button>
        )}
        {hasResume === false && (
          <span className="text-sm text-gray-500 dark:text-gray-400">
            No CV yet —{" "}
            <Link href="/profile" className="underline">
              add one
            </Link>{" "}
            to get started.
          </span>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-sm text-gray-500 dark:text-gray-400">Fetch from</span>
        {(status?.sources?.length ? status.sources : SOURCE_ORDER).map((source) => (
          <SourceToggle
            key={source}
            active={sources.has(source)}
            disabled={status?.running}
            onClick={() => toggleSource(source)}
          >
            {SOURCE_LABELS[source] ?? source}
          </SourceToggle>
        ))}
        {sources.size === 0 && (
          <span className="text-xs text-gray-400 dark:text-gray-600">
            nothing to fetch — just re-scores what&apos;s already stored
          </span>
        )}
      </div>

      {status?.running && (
        <div className="mt-5 rounded-lg border border-gray-200 p-4 dark:border-gray-800">
          <div className="flex justify-center">
            <PhaseStepper phases={status.phases?.length ? status.phases : PHASE_ORDER} current={status.phase} />
          </div>

          <div className="mt-3 flex flex-wrap items-center justify-center gap-2 text-sm text-gray-600 dark:text-gray-300">
            <span className="h-2.5 w-2.5 animate-spin rounded-full border-2 border-gray-400 border-t-transparent" />
            {status.phase === "score"
              ? `scoring ${bar?.done ?? 0}/${bar?.total ?? 0}`
              : status.phase === "ingest" && status.progress
                ? `fetching ${status.progress.source}: ${status.progress.done}/${status.progress.total}`
                : `${PHASE_LABELS[status.phase ?? ""] ?? "starting"}…`}
            {etaLabel && <span className="text-gray-400 dark:text-gray-600">~{etaLabel} left</span>}
          </div>

          {bar && (
            <div className="mx-auto mt-2 h-1.5 w-full max-w-xs overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
              <div
                className="h-full rounded-full bg-black transition-all duration-500 dark:bg-white"
                style={{ width: `${barPct}%` }}
              />
            </div>
          )}
          {status.phase === "score" && jobsLine && (
            <p className="mt-1.5 text-center text-xs text-gray-500 dark:text-gray-400">{jobsLine}</p>
          )}
          <p className="mt-2 text-center text-xs tabular-nums text-gray-400 dark:text-gray-600">
            {formatDuration(elapsedSec)} elapsed
          </p>
        </div>
      )}

      {toast && (
        <div className="mt-4 flex items-center gap-2.5 rounded-lg border border-gray-200 bg-gray-50 px-4 py-2.5 text-sm dark:border-gray-800 dark:bg-gray-900">
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-black text-[10px] text-white dark:bg-white dark:text-black">
            ✓
          </span>
          <span>
            Run complete — {toast.completed} scored{toast.failed ? `, ${toast.failed} failed` : ""}.
          </span>
          <button
            onClick={() => setToast(null)}
            className="ml-auto text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
            aria-label="Dismiss"
          >
            ✕
          </button>
        </div>
      )}

      {(error || status?.last_error) && (
        <p className="mt-3 text-sm text-red-600 dark:text-red-400">
          {error ?? `Last run failed: ${status?.last_error}`}
        </p>
      )}

      <h2 className="mt-10 text-lg font-semibold">Shortlist</h2>

      <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-3 border-y border-gray-200 py-3 dark:border-gray-800">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-gray-500 dark:text-gray-400">Sort</span>
          {SORTS.map((option) => (
            <Chip
              key={option.value}
              active={sort === option.value}
              onClick={() => {
                setSort(option.value);
                setPageIndex(0); // a new order makes the old offset meaningless
              }}
            >
              {option.label}
            </Chip>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-gray-500 dark:text-gray-400">Work mode</span>
          {MODES.map((option) => (
            <Chip
              key={option.value}
              active={remote === option.value}
              onClick={() => {
                setRemote(option.value);
                setPageIndex(0);
              }}
            >
              {option.label}
            </Chip>
          ))}
        </div>
      </div>

      <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
        {page.total === 0 ? "No matches" : `Showing ${first}–${last} of ${page.total}`}
      </p>

      <ul className="mt-4 space-y-4">
        {page.items.map((item) => (
          <li key={item.url} className="rounded-lg border border-gray-200 p-4 dark:border-gray-800">
            <div className="flex items-baseline gap-3">
              <span className="rounded bg-green-100 px-2 py-0.5 text-sm font-bold text-green-800 dark:bg-green-900 dark:text-green-200">
                {item.score}
              </span>
              <a
                href={item.url}
                target="_blank"
                rel="noreferrer"
                className="font-medium hover:underline"
              >
                {item.title}
              </a>
              <span className="text-sm text-gray-500 dark:text-gray-400">
                {item.company ?? "?"}
              </span>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
              {item.remote !== null && (
                <span className="rounded bg-gray-100 px-1.5 py-0.5 dark:bg-gray-800">
                  {item.remote ? "Remote" : "On-site"}
                </span>
              )}
              {item.location && <span>{item.location}</span>}
              {daysAgo(item.posted_at) && <span>· {daysAgo(item.posted_at)}</span>}
            </div>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">{item.summary}</p>
          </li>
        ))}
        {page.total === 0 && (
          <li className="text-sm text-gray-500 dark:text-gray-400">
            {remote
              ? "Nothing matches this work mode — try Any."
              : "Nothing yet — run it to populate the shortlist."}
          </li>
        )}
      </ul>

      {page.total > PAGE_SIZE && (
        <div className="mt-6 flex items-center gap-4 text-sm">
          <button
            onClick={() => setPageIndex((i) => i - 1)}
            disabled={pageIndex === 0}
            className="rounded-lg border border-gray-300 px-3 py-1.5 disabled:opacity-40 dark:border-gray-700"
          >
            ← Previous
          </button>
          <span className="text-gray-500 dark:text-gray-400">
            Page {pageIndex + 1} of {lastPage + 1}
          </span>
          <button
            onClick={() => setPageIndex((i) => i + 1)}
            disabled={pageIndex >= lastPage}
            className="rounded-lg border border-gray-300 px-3 py-1.5 disabled:opacity-40 dark:border-gray-700"
          >
            Next →
          </button>
        </div>
      )}
    </main>
  );
}
