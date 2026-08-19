# Architecture

One weekly run, one user. Postings come in from several sources, retrieval picks
the handful worth an LLM call, the scorer sees only the resume sections that
answer each posting.

```mermaid
flowchart TD
    subgraph PHASE_INGEST["phase: ingest — sources selectable per run"]
        ED[czyjesteldorado scraper] --> JP
        BD["boards.json boards<br/>(add-your-own, no code)"] --> JP
        GM["Gmail job alerts (IMAP)<br/>mail → Trash once stored"] --> JP
    end
    RO["RemoteOK JSON API<br/>(CLI only — cli.ingest_remoteok,<br/>not wired into run_pipeline)"] -.-> JP

    JP[("job_postings<br/>embedding + search_vector")]

    JP --> EMB["phase: embed<br/>embed_new_postings(), batched"]

    CV[["resume text"]] --> KW["extract_keywords()"]
    CV --> RC[("resume_chunks<br/>section + embedding")]

    KW --> Q{{"queries = keywords + full resume"}}
    EMB --> Q

    subgraph PHASE_RETRIEVE["phase: retrieve"]
        Q --> QV["embed() — one batched call<br/>for every query vector"]
        QV --> DENSE["dense channel<br/>cosine on embedding"]
        Q --> LEX["lexical channel<br/>websearch_to_tsquery"]
        DENSE --> RRF["RRF fusion → top 25"]
        LEX --> RRF
    end

    RRF --> MJ[("match_jobs<br/>one per retrieved posting")]

    subgraph PHASE_SCORE["phase: score"]
        MJ --> CTX["build_resume_context()<br/>top-3 chunks + full keyword list"]
        RC --> CTX
        CTX --> LLM["LLM score 0-100<br/>+ summary quoting the resume"]
    end

    LLM --> MO[("match_outputs")]
    MO --> OUT["phase: done<br/>shortlist ≥ 60 — Next.js page / email digest"]
    OUT --> APPLY["cli.apply N<br/>fills the form in a real browser,<br/>stops before Submit"]
```

`GET /pipeline/status` reports the current phase (`ingest → embed → retrieve → score → done`)
plus per-source progress (`{source, done, total}`) during ingest, so the UI can render a
stepper. `POST /pipeline/stop` cancels the in-flight run; `POST /pipeline/run` accepts an
optional `sources` list to ingest from a subset (or `[]` to skip ingest and just
re-retrieve/re-score what's already stored).

## What does what

| Module | Responsibility |
| --- | --- |
| `services/ingest_remoteok.py` | RemoteOK's free JSON feed → posting rows |
| `services/ingest_eldorado.py` | czyjesteldorado search + detail pages → posting rows |
| `services/ingest_board.py` | `boards.json`-defined boards (schema.org `JobPosting` scrape) → posting rows |
| `services/ingest_gmail.py` | IMAP read of job-alert senders, LLM extraction per mail, mail → Trash after storing |
| `database/operations/job_posting.py` | upsert on `(source, source_id)` — reruns refresh, never duplicate |
| `services/extract_keywords.py` | resume → ≤10 search keywords (also the "complete skill list" the scorer trusts) |
| `services/embeddings.py` | batched embedding calls, 8k-char input cap |
| `services/retrieve.py` | dense + lexical ranking per query, RRF fusion, backfill of posting vectors |
| `services/resume_chunks.py` | resume → sections → embeddings; per-posting context assembly |
| `services/match.py` | MatchJob lifecycle, the scoring prompt, shortlist query |
| `services/pipeline.py` | the weekly run, in order; shared by CLI and HTTP |
| `endpoints/profile.py` | the stored CV: markdown/plain text, or a PDF whose text layer is extracted here |
| `endpoints/pipeline.py` | `POST /pipeline/run` (optional `sources`), `POST /pipeline/stop`, `GET /pipeline/status` (phase + per-source progress), `GET /shortlist` (paged) |
| `cli/match_pipeline.py` | the weekly entrypoint a cron actually calls |
| `cli/ingest_gmail.py` | the daily mail-only entrypoint |
| `cli/apply.py` | opens a shortlisted offer's form in a real browser, fills it, stops before Submit |

## Where the cost is

Embeddings are rounding-error cheap; the scoring call is not. Two things bound it:
retrieval caps how many postings get scored (`retrieval_top_k`, default 50), and
`build_resume_context` sends 3 resume sections instead of the whole CV.

`match_jobs` rows are never re-scored, so a rerun on the same day costs almost nothing.
