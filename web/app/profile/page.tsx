"use client";

import Link from "next/link";
import { Icon } from "@/components/icons";
import { useEffect, useRef, useState } from "react";
import { errorDetail } from "@/lib/errorDetail";

type StoredResume = {
  text: string;
  keywords: string[] | null;
  updated_at: string;
};

export default function Profile() {
  const [text, setText] = useState("");
  const [stored, setStored] = useState<StoredResume | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch("/api/profile/resume")
      .then((r) => r.json())
      .then((data: StoredResume | null) => {
        if (data) {
          setStored(data);
          setText(data.text);
        }
      })
      .catch(() => setError("Can't reach the server. Check your connection and try again in a moment."));
  }, []);

  async function send(path: string, init: RequestInit) {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const res = await fetch(path, { method: "PUT", ...init });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        setError(errorDetail(body, "Save failed"));
        return;
      }
      setStored(body);
      setText(body.text);
      setSaved(true);
    } catch {
      setError("Can't reach the server. Check your connection and try again in a moment.");
    } finally {
      setBusy(false);
    }
  }

  async function onPickPdf(file: File) {
    await send("/api/profile/resume/pdf", { body: await file.arrayBuffer() });
    if (fileInput.current) fileInput.current.value = ""; // so the same file can be re-picked
  }

  const dirty = text.trim() !== (stored?.text ?? "");

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  return (
    <main className="mx-auto max-w-4xl px-6 py-16 sm:py-24">
      <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-ink">
        <Icon name="arrow" back />Your matches
      </Link>
      <h1 className="mt-4 text-4xl sm:text-5xl">Profile</h1>
      <p className="mt-3 text-muted">
        Your CV is saved once and used for every search. Upload a PDF or paste the text.
      </p>

      <div className="mt-10 flex flex-wrap items-center gap-3">
        <button
          onClick={() => fileInput.current?.click()}
          disabled={busy}
          className="rounded-md bg-ink px-5 py-2 text-sm font-medium text-on-ink transition-colors hover:bg-ink-hover disabled:opacity-40"
        >
          Upload PDF…
        </button>
        <input
          ref={fileInput}
          type="file"
          accept="application/pdf"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onPickPdf(file);
          }}
        />
        <span className="text-sm text-muted">
          Works with PDFs where you can select the text. Scanned images aren&apos;t supported.
        </span>
      </div>

      <textarea
        aria-label="CV text"
        name="resume"
        autoComplete="off"
        spellCheck={false}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Paste your CV text here…"
        className="mt-4 h-96 w-full resize-y rounded-lg border border-line bg-surface p-6 font-mono text-sm text-body placeholder:text-muted"
      />

      <div className="mt-4 flex flex-wrap items-center gap-4">
        <button
          onClick={() => send("/api/profile/resume", { body: JSON.stringify({ text }) })}
          disabled={busy || !dirty || text.trim().length < 50}
          className="rounded-md bg-ink px-5 py-2 text-sm font-medium text-on-ink transition-colors hover:bg-ink-hover disabled:opacity-40"
        >
          {busy ? "Saving…" : "Save CV"}
        </button>
        <span aria-live="polite" className="text-sm text-muted">
          {text.trim().length < 50
            ? "Add at least 50 characters to save"
            : dirty
              ? "You have unsaved changes"
              : saved
                ? "Saved"
                : stored
                  ? `Saved ${new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(stored.updated_at))}`
                  : ""}
        </span>
      </div>

      {stored && !dirty && !busy && (
        <Link
          href="/"
          className="mt-6 inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-5 py-2 text-sm font-medium text-body transition-colors hover:border-muted"
        >
          Find jobs with this CV<Icon name="arrow" />
        </Link>
      )}

      {error && <p role="alert" className="mt-3 rounded-md bg-red-bg px-3 py-2 text-sm text-red-fg">{error}</p>}

      {stored?.keywords?.length ? (
        <>
          <h2 className="mt-20 text-3xl">Search keywords</h2>
          <p className="mt-2 text-sm text-muted">
            Extracted from this CV on the last run — these drive scraping and retrieval.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {stored.keywords.map((keyword) => (
              <span
                key={keyword}
                className="rounded-full bg-chip px-3 py-1 font-mono text-xs uppercase tracking-[0.05em] text-body"
              >
                {keyword}
              </span>
            ))}
          </div>
        </>
      ) : null}
    </main>
  );
}
