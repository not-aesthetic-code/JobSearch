"use client";

import Link from "next/link";
import { Icon } from "@/components/icons";
import { useCallback, useEffect, useRef, useState } from "react";
import { errorDetail } from "@/lib/errorDetail";
import { usePipelineProgress, type PipelineStatus } from "@/lib/usePipelineProgress";

type ShortlistItem = {
  id: string;
  seen: boolean;
  applied: boolean;
  score: number;
  summary: string;
  title: string;
  company: string | null;
  url: string;
  remote: boolean | null;
  location: string | null;
  posted_at: string | null;
  seniority: "junior" | "mid" | "senior" | null;
};

type ShortlistPage = {
  items: ShortlistItem[];
  total: number;
};

const PAGE_SIZE = 10;
const SERVER_DOWN = "Can't reach the server. Check your connection and try again in a moment.";

const SOURCE_ORDER = ["eldorado", "boards"]; // gmail disabled server-side
const SOURCE_LABELS: Record<string, string> = {
  eldorado: "Eldorado",
  boards: "Job boards",
  gmail: "Gmail alerts",
};

const PHASE_ORDER = ["ingest", "embed", "retrieve", "score", "done"];
const PHASE_LABELS: Record<string, string> = {
  ingest: "Collecting",
  embed: "Preparing",
  retrieve: "Matching",
  score: "Ranking",
  done: "Done",
};

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
                aria-hidden="true"
                className={
                  state === "done"
                    ? "flex h-5 w-5 items-center justify-center rounded-full bg-ink text-on-ink"
                    : state === "active"
                      ? "flex h-5 w-5 items-center justify-center rounded-full border-2 border-ink"
                      : "flex h-5 w-5 items-center justify-center rounded-full border border-line"
                }
              >
                {state === "done" && <Icon name="check" className="h-2.5 w-2.5" />}
              </span>
              <span
                className={`text-[11px] ${
                  state === "pending" ? "text-muted" : "text-body"
                }`}
              >
                {PHASE_LABELS[p] ?? p}
              </span>
            </div>
            {i < phases.length - 1 && (
              <span
                className={`mx-1.5 mb-4 h-px w-8 shrink-0 ${
                  state === "done" ? "bg-ink" : "bg-line"
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

const LEVELS = [
  { value: "", label: "Senior & mid" },
  { value: "true", label: "Include junior" },
] as const;

const MODES = [
  { value: "", label: "Any" },
  { value: "true", label: "Remote" },
  { value: "false", label: "On-site" },
] as const;

// "" defers to the backend's configured match_threshold (currently 60)
const MIN_SCORES = [
  { value: "", label: "Best matches" },
  { value: "40", label: "40+" },
  { value: "20", label: "20+" },
  { value: "0", label: "All" },
] as const;

function scoreColor(score: number) {
  if (score >= 60) return "bg-green-bg text-green-fg";
  if (score >= 40) return "bg-yellow-bg text-yellow-fg";
  return "bg-chip text-muted";
}

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
      className={`rounded-md border px-3 py-1 text-sm transition-colors disabled:opacity-40 ${
        active
          ? "border-ink bg-ink text-on-ink"
          : "border-line bg-surface text-body hover:border-muted"
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
      className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1 text-sm text-body transition-colors hover:border-muted disabled:opacity-40"
    >
      <span
        aria-hidden="true"
        className={`flex h-3.5 w-3.5 items-center justify-center rounded-sm border ${
          active
            ? "border-ink bg-ink text-on-ink"
            : "border-muted"
        }`}
      >
        {active && <Icon name="check" className="h-2 w-2" />}
      </span>
      {children}
    </button>
  );
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
  const [minScore, setMinScore] = useState<string>("");
  const [junior, setJunior] = useState<string>("");
  const [hasResume, setHasResume] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sources, setSources] = useState<Set<string>>(new Set(SOURCE_ORDER));
  const { toast, dismissToast, bar, barPct, elapsedLabel, etaLabel, jobsLine } = usePipelineProgress(status);

  const loading = status === null && !error;
  const latestRequest = useRef(0); // polling + filter clicks overlap; only the newest response may render

  // optimistic: flip the card now, tell the server after; a failed call is corrected by the next refresh
  const act = useCallback(async (id: string, action: "seen" | "applied" | "dismissed" | "apply") => {
    if (action === "dismissed") {
      setPage((p) => ({ items: p.items.filter((it) => it.id !== id), total: p.total - 1 }));
    } else if (action !== "apply") {
      const key = action === "seen" ? "seen" : "applied";
      setPage((p) => ({ ...p, items: p.items.map((it) => (it.id === id ? { ...it, [key]: true } : it)) }));
    }
    try {
      const res = await fetch(`/api/shortlist/${id}/${action}`, { method: "POST" });
      if (!res.ok && action === "apply") setError(errorDetail(await res.json().catch(() => null)));
    } catch {
      setError(SERVER_DOWN);
    }
  }, []);

  const refresh = useCallback(async () => {
    const requestId = ++latestRequest.current;
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(pageIndex * PAGE_SIZE),
      sort,
    });
    if (remote) params.set("remote", remote);
    if (minScore) params.set("min_score", minScore);
    if (junior) params.set("junior", junior);
    try {
      const [statusRes, listRes, resumeRes] = await Promise.all([
        fetch("/api/pipeline/status"),
        fetch(`/api/shortlist?${params}`),
        fetch("/api/profile/resume"),
      ]);
      const [nextStatus, nextPage, resume] = await Promise.all([statusRes.json(), listRes.json(), resumeRes.json()]);
      if (requestId !== latestRequest.current) return;
      setStatus(nextStatus);
      setPage(nextPage);
      setHasResume(resume !== null);
      setError(null);
    } catch {
      setError(SERVER_DOWN);
    }
  }, [pageIndex, sort, remote, minScore, junior]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // poll while a run is in progress
  useEffect(() => {
    if (!status?.running) return;
    const timer = setInterval(refresh, 1500);
    return () => clearInterval(timer);
  }, [status?.running, refresh]);

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
    try {
      const res = await fetch("/api/pipeline/run", {
        method: "POST",
        headers: { "content-type": "application/json" },
        // no resume_text = use the CV stored in the profile; sources = [] just
        // re-retrieves/re-scores whatever is already ingested, no fetching at all
        body: JSON.stringify({ sources: [...sources] }),
      });
      if (!res.ok) {
        setError(errorDetail(await res.json().catch(() => null)));
        return;
      }
    } catch {
      setError(SERVER_DOWN);
      return;
    }
    refresh();
  }

  async function stop() {
    setError(null);
    try {
      const res = await fetch("/api/pipeline/stop", { method: "POST" });
      if (!res.ok) {
        setError(errorDetail(await res.json().catch(() => null)));
        return;
      }
    } catch {
      setError(SERVER_DOWN);
      return;
    }
    refresh();
  }

  const lastPage = Math.max(0, Math.ceil(page.total / PAGE_SIZE) - 1);
  const first = page.total === 0 ? 0 : pageIndex * PAGE_SIZE + 1;
  const last = Math.min(page.total, (pageIndex + 1) * PAGE_SIZE);

  return (
    <main className="mx-auto max-w-4xl px-6 py-16 sm:py-24">
      <div className="flex items-baseline justify-between gap-4">
        <h1 className="text-4xl sm:text-5xl">Job Search</h1>
        <Link href="/profile" className="inline-flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-ink">
          Profile<Icon name="arrow" />
        </Link>
      </div>
      <p className="mt-3 text-muted">
        Finds jobs that match your CV and ranks them for you.
      </p>

      {hasResume === false && (
        <div className="mt-10 rounded-lg border border-line bg-surface p-8">
          <h2 className="text-2xl">Start by adding your CV</h2>
          <p className="mt-2 text-sm text-muted">
            Upload a PDF or paste the text. It takes about 10 seconds, and then we find the matching jobs.
          </p>
          <Link
            href="/profile"
            className="mt-5 inline-block rounded-md bg-ink px-5 py-2 text-sm font-medium text-on-ink transition-colors hover:bg-ink-hover disabled:opacity-40"
          >
            Add your CV
          </Link>
        </div>
      )}

      <div className={`mt-10 flex flex-wrap items-center gap-3 ${hasResume === false ? "hidden" : ""}`}>
        <button
          onClick={run}
          disabled={status?.running || hasResume !== true}
          className="rounded-md bg-ink px-5 py-2 text-sm font-medium text-on-ink transition-colors hover:bg-ink-hover disabled:opacity-40"
        >
          {status?.running ? "Searching…" : "Find Jobs"}
        </button>
        {status?.running && (
          <button
            onClick={stop}
            className="rounded-md border border-line bg-surface px-5 py-2 text-sm font-medium text-body transition-colors hover:border-muted"
          >
            Stop
          </button>
        )}
      </div>

      <details className={`mt-3 ${hasResume === false ? "hidden" : ""}`}>
        <summary className="cursor-pointer text-sm text-muted">Advanced: choose sources</summary>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted">Search in</span>
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
          <span className="text-xs text-muted">
            No source selected — only re-ranks jobs you already have.
          </span>
        )}
      </div>
      </details>

      {status?.running && (
        <div role="status" aria-live="polite" className="mt-6 rounded-lg border border-line bg-surface p-6">
          <div className="flex justify-center">
            <PhaseStepper phases={status.phases?.length ? status.phases : PHASE_ORDER} current={status.phase} />
          </div>

          <div className="mt-3 flex flex-wrap items-center justify-center gap-2 text-sm text-body">
            <span aria-hidden="true" className="h-2.5 w-2.5 animate-spin motion-reduce:animate-none rounded-full border-2 border-muted border-t-transparent" />
            {status.phase === "score"
              ? `Ranking ${bar?.done ?? 0} of ${bar?.total ?? 0} jobs`
              : status.phase === "ingest" && status.progress
                ? `Collecting jobs from ${SOURCE_LABELS[status.progress.source] ?? status.progress.source}: ${status.progress.done} of ${status.progress.total}`
                : `${PHASE_LABELS[status.phase ?? ""] ?? "starting"}…`}
            {etaLabel && <span className="text-muted">~{etaLabel} left</span>}
          </div>

          {bar && (
            <div className="mx-auto mt-2 h-1.5 w-full max-w-xs overflow-hidden rounded-full bg-chip">
              <div
                className="h-full rounded-full bg-ink transition-[width] duration-500"
                style={{ width: `${barPct}%` }}
              />
            </div>
          )}
          {status.phase === "score" && jobsLine && (
            <p className="mt-1.5 text-center text-xs text-muted">{jobsLine}</p>
          )}
          <p className="mt-2 text-center font-mono text-xs tabular-nums text-muted">
            {elapsedLabel} elapsed
          </p>
        </div>
      )}

      {toast && (
        <div role="status" aria-live="polite" className="mt-4 flex items-center gap-2.5 rounded-lg border border-line bg-green-bg px-4 py-2.5 text-sm text-green-fg">
          <span aria-hidden="true" className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-green-fg text-green-bg">
            <Icon name="check" className="h-2.5 w-2.5" />
          </span>
          <span>
            Done — {toast.completed} jobs ranked{toast.failed ? `, ${toast.failed} failed` : ""}.
          </span>
          <button
            onClick={dismissToast}
            className="ml-auto opacity-60 hover:opacity-100"
            aria-label="Dismiss"
          >
            <Icon name="x" />
          </button>
        </div>
      )}

      {(error || status?.last_error) && (
        <p role="alert" className="mt-3 rounded-md bg-red-bg px-3 py-2 text-sm text-red-fg">
          {error ?? `The last search failed: ${status?.last_error}. Try again.`}
        </p>
      )}

      <h2 className="mt-20 text-3xl">Your matches</h2>

      <div className="mt-5 flex flex-wrap items-center gap-x-8 gap-y-3 border-y border-line py-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted">Sort</span>
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
          <span className="text-sm text-muted">Work mode</span>
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
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted">Level</span>
          {LEVELS.map((option) => (
            <Chip
              key={option.value}
              active={junior === option.value}
              onClick={() => {
                setJunior(option.value);
                setPageIndex(0);
              }}
            >
              {option.label}
            </Chip>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted" title="How well a job fits your CV, 0–100">Match score</span>
          {MIN_SCORES.map((option) => (
            <Chip
              key={option.value}
              active={minScore === option.value}
              onClick={() => {
                setMinScore(option.value);
                setPageIndex(0);
              }}
            >
              {option.label}
            </Chip>
          ))}
        </div>
      </div>

      <p className="mt-4 text-sm text-muted">
        {loading ? "Loading…" : page.total === 0 ? "No matches" : `Showing ${first}–${last} of ${page.total.toLocaleString()}`}
      </p>

      <ul className="mt-4 space-y-3">
        {page.items.map((item, i) => (
          <li
            key={`${item.url}-${i}`}
            style={{ "--index": Math.min(i, 8) } as React.CSSProperties}
            className={`card rise relative rounded-lg border border-line bg-surface p-6 ${
              item.applied ? "opacity-60" : item.seen ? "opacity-80" : ""
            }`}
          >
            <button
              onClick={() => act(item.id, "dismissed")}
              aria-label={`Remove ${item.title} from the list`}
              title="Remove from list"
              className="absolute right-3 top-3 rounded-md p-1.5 text-muted transition-colors hover:text-ink"
            >
              <Icon name="x" className="h-3 w-3" />
            </button>
            <div className="flex items-baseline gap-3 pr-8">
              <span className={`shrink-0 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium uppercase tracking-[0.05em] tabular-nums ${scoreColor(item.score)}`}>
                {item.score}% match
              </span>
              <a
                href={item.url}
                target="_blank"
                rel="noreferrer"
                onClick={() => !item.seen && act(item.id, "seen")}
                className="min-w-0 break-words font-medium text-ink hover:underline"
              >
                {item.title}
                <span className="sr-only"> (opens in new tab)</span>
              </a>
              <span className="text-sm text-muted">
                {item.company ?? "Company not listed"}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
              {item.remote !== null && (
                <span className="rounded-full bg-blue-bg px-2 py-0.5 uppercase tracking-[0.05em] text-blue-fg">
                  {item.remote ? "Remote" : "On-site"}
                </span>
              )}
              {item.seniority && (
                <span className="rounded-full bg-blue-bg px-2 py-0.5 uppercase tracking-[0.05em] text-blue-fg">
                  {item.seniority}
                </span>
              )}
              {item.location && <span>{item.location}</span>}
              {daysAgo(item.posted_at) && <span>· {daysAgo(item.posted_at)}</span>}
            </div>
            <p className="mt-3 line-clamp-3 text-sm text-body">{item.summary}</p>
            <div className="mt-4 flex items-center gap-2 text-sm">
              {item.applied ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-green-bg px-3 py-1 text-green-fg">
                  <Icon name="check" className="h-3 w-3" />Applied
                </span>
              ) : (
                <>
                  <button
                    onClick={() => act(item.id, "apply")}
                    title="Opens a browser on this machine and fills the form. You review and click Send."
                    className="rounded-md border border-line bg-surface px-3 py-1 text-body transition-colors hover:border-muted"
                  >
                    Auto-fill application
                  </button>
                  <button
                    onClick={() => act(item.id, "applied")}
                    className="rounded-md px-3 py-1 text-muted transition-colors hover:text-ink"
                  >
                    Mark as applied
                  </button>
                </>
              )}
            </div>
          </li>
        ))}
        {!loading && page.total === 0 && (
          <li className="text-sm text-muted">
            {remote || minScore
              ? "Nothing matches these filters. Try \"Any\" work mode or \"All\" match scores."
              : hasResume === false
                ? "Add your CV above to get your first matches."
                : "No matches yet. Click \"Find Jobs\" to get your first results."}
          </li>
        )}
      </ul>

      {page.total > PAGE_SIZE && (
        <div className="mt-8 flex items-center gap-4 text-sm">
          <button
            onClick={() => setPageIndex((i) => i - 1)}
            disabled={pageIndex === 0}
            className="rounded-md border border-line bg-surface px-3 py-1.5 hover:border-muted disabled:opacity-40"
          >
            <Icon name="arrow" back className="mr-1.5 h-3 w-3" />Previous
          </button>
          <span className="text-muted">
            Page {pageIndex + 1} of {lastPage + 1}
          </span>
          <button
            onClick={() => setPageIndex((i) => i + 1)}
            disabled={pageIndex >= lastPage}
            className="rounded-md border border-line bg-surface px-3 py-1.5 hover:border-muted disabled:opacity-40"
          >
            Next<Icon name="arrow" className="ml-1.5 h-3 w-3" />
          </button>
        </div>
      )}
    </main>
  );
}
