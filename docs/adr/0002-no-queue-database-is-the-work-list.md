# ADR 0002 — No task queue: `match_jobs` is the work list

- **Status:** Accepted
- **Date:** 2026-08-12

## Context

A weekly run does two things that can fail halfway: it hits several job boards,
and it makes one LLM call per retrieved posting. The second is slow (tens of
seconds of wall clock per batch) and each call can fail on its own — a rate limit,
a malformed posting, a truncated response.

The reflex architecture for that is Celery or arq with Redis: enqueue one task per
posting, let workers retry. This project has one user, one run a week, and tens of
scoring calls per run.

## Decision

The `match_jobs` table *is* the queue. Each row is one `(user, job_posting)` scoring
job with a `pending → processing → completed | failed` lifecycle, an `attempt_count`,
and `error_code` / `error_message` when it fails.

`process_match_jobs` walks the pending rows and commits after each one, so:

- a crash mid-run loses at most the single job in flight;
- a rerun picks up exactly what is still `pending` — no bookkeeping, no dedupe pass;
- one bad posting cannot kill the run (the scoring call is wrapped, the row goes
  `failed` with the exception recorded, the loop continues);
- a `UNIQUE (user_id, job_posting_id)` constraint means the same posting is never
  scored twice for the same user, even if retrieval surfaces it again next week.

No Redis, no worker process, no broker. The remote deployment is Postgres plus a
weekly cron running `cli.match_pipeline`.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Celery / arq + Redis | A broker, a worker process and a second datastore to operate, so that a weekly batch of tens of jobs can retry. The retry semantics already exist in the status column. |
| `asyncio.gather` over all postings | Faster, but bursts straight into provider rate limits and makes partial failure harder to reason about. Scoring is sequential on purpose; a semaphore is the upgrade if a run ever gets too slow. |
| Score inline during ingestion, no job rows | No record of what failed and why, and no way to resume a half-finished run without re-scoring what succeeded. |
| Postgres `SELECT … FOR UPDATE SKIP LOCKED` | The correct pattern for *concurrent* workers. There is one worker, so the locking buys nothing today. It is the natural next step if scoring is ever parallelised. |

## Consequences

- Sequential scoring means run time grows linearly with retrieved postings.
  `retrieval_top_k` (default 25) is the real throttle.
- Failed jobs are never retried automatically — they sit `failed` until something
  resets them to `pending`. Deliberate: an unattended weekly job that retries
  LLM calls on its own is how a personal project runs up a bill.
- `POST /pipeline/run` tracks "is a run in progress" in a module-level flag, which
  is correct only for a single-worker deployment. Two uvicorn workers would each
  believe they are the only one; the fix is a row in Postgres, not a queue.
- Anyone reading this repo for the multi-agent pattern in the article that inspired
  it will not find one. The pipeline is a straight line: ingest → embed → retrieve →
  score. An agent graph adds branching and retry semantics that a linear weekly
  batch does not need.
