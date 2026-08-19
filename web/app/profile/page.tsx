"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

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
      .catch(() => setError("Backend unreachable — is the FastAPI server running?"));
  }, []);

  async function send(path: string, init: RequestInit) {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const res = await fetch(path, { method: "PUT", ...init });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        setError(typeof body?.detail === "string" ? body.detail : "Save failed");
        return;
      }
      setStored(body);
      setText(body.text);
      setSaved(true);
    } catch {
      setError("Backend unreachable — is the FastAPI server running?");
    } finally {
      setBusy(false);
    }
  }

  async function onPickPdf(file: File) {
    await send("/api/profile/resume/pdf", { body: await file.arrayBuffer() });
    if (fileInput.current) fileInput.current.value = ""; // so the same file can be re-picked
  }

  const dirty = text.trim() !== (stored?.text ?? "");

  return (
    <main className="mx-auto max-w-3xl px-6 py-12 font-sans">
      <Link href="/" className="text-sm text-gray-500 hover:underline dark:text-gray-400">
        ← Shortlist
      </Link>
      <h1 className="mt-2 text-2xl font-bold">Profile</h1>
      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
        Your CV, stored once. Every run matches against it — paste markdown or upload a PDF.
      </p>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button
          onClick={() => fileInput.current?.click()}
          disabled={busy}
          className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium disabled:opacity-40 dark:border-gray-700"
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
        <span className="text-sm text-gray-500 dark:text-gray-400">
          text layer only — a scanned PDF won&apos;t work
        </span>
      </div>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="# Jane Doe&#10;Senior Backend Engineer…"
        className="mt-4 h-96 w-full resize-y rounded-lg border border-gray-300 bg-transparent p-3 font-mono text-sm dark:border-gray-700"
      />

      <div className="mt-3 flex flex-wrap items-center gap-4">
        <button
          onClick={() => send("/api/profile/resume", { body: JSON.stringify({ text }) })}
          disabled={busy || !dirty || text.trim().length < 50}
          className="rounded-lg bg-black px-5 py-2 text-sm font-medium text-white disabled:opacity-40 dark:bg-white dark:text-black"
        >
          {busy ? "Saving…" : "Save CV"}
        </button>
        <span className="text-sm text-gray-500 dark:text-gray-400">
          {text.trim().length < 50
            ? "at least 50 characters"
            : dirty
              ? "unsaved changes"
              : saved
                ? "saved"
                : stored
                  ? `saved ${new Date(stored.updated_at).toLocaleString()}`
                  : ""}
        </span>
      </div>

      {error && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}

      {stored?.keywords?.length ? (
        <>
          <h2 className="mt-10 text-lg font-semibold">Search keywords</h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Extracted from this CV on the last run — these drive scraping and retrieval.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {stored.keywords.map((keyword) => (
              <span
                key={keyword}
                className="rounded-full bg-gray-100 px-3 py-1 text-sm dark:bg-gray-800"
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
