"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

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
  jobs: Record<string, number>;
  last_error: string | null;
};

const PAGE_SIZE = 10;

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
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full border px-3 py-1 text-sm transition-colors ${
        active
          ? "border-black bg-black text-white dark:border-white dark:bg-white dark:text-black"
          : "border-gray-300 text-gray-600 hover:border-gray-400 dark:border-gray-700 dark:text-gray-300"
      }`}
    >
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
  const [hasResume, setHasResume] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
  }, [status?.running, refresh]);

  async function run() {
    setError(null);
    const res = await fetch("/api/pipeline/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}", // no resume_text = use the CV stored in the profile
    });
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
        {hasResume === false && (
          <span className="text-sm text-gray-500 dark:text-gray-400">
            No CV yet —{" "}
            <Link href="/profile" className="underline">
              add one
            </Link>{" "}
            to get started.
          </span>
        )}
        {status?.running && (
          <span className="text-sm text-gray-500 dark:text-gray-400">
            scraping &amp; scoring — this takes a few minutes
          </span>
        )}
        {jobsLine && <span className="text-sm text-gray-500 dark:text-gray-400">{jobsLine}</span>}
      </div>

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
