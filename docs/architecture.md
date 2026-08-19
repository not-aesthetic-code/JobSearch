# Architecture

One weekly run, one user. Postings come in from several sources, retrieval picks
the handful worth an LLM call, the scorer sees only the resume sections that
answer each posting.

```mermaid
flowchart TD
    RO[RemoteOK JSON API] --> JP
    ED[czyjesteldorado scraper] --> JP
    GM["Gmail job alerts (IMAP)<br/>mail → Trash once stored"] --> JP

    JP[("job_postings<br/>embedding + search_vector")] --> EMB["embed_new_postings()<br/>fills missing vectors"]

    CV[["resume text"]] --> KW["extract_keywords()"]
    CV --> RC[("resume_chunks<br/>section + embedding")]

    KW --> Q{{"queries = keywords + full resume"}}
    EMB --> Q

    Q --> DENSE["dense channel<br/>cosine on embedding"]
    Q --> LEX["lexical channel<br/>websearch_to_tsquery"]
    DENSE --> RRF["RRF fusion → top 25"]
    LEX --> RRF

    RRF --> MJ[("match_jobs<br/>one per retrieved posting")]
    MJ --> CTX["build_resume_context()<br/>top-3 chunks + full keyword list"]
    RC --> CTX
    CTX --> LLM["LLM score 0-100<br/>+ summary quoting the resume"]
    LLM --> MO[("match_outputs")]
    MO --> OUT["shortlist ≥ 60<br/>Next.js page / email digest"]
    OUT --> APPLY["cli.apply N<br/>fills the form in a real browser,<br/>stops before Submit"]
```

## What does what

| Module | Responsibility |
| --- | --- |
| `services/ingest_remoteok.py` | RemoteOK's free JSON feed → posting rows |
| `services/ingest_eldorado.py` | czyjesteldorado search + detail pages → posting rows |
| `services/ingest_gmail.py` | IMAP read of job-alert senders, LLM extraction per mail, mail → Trash after storing |
| `database/operations/job_posting.py` | upsert on `(source, source_id)` — reruns refresh, never duplicate |
| `services/extract_keywords.py` | resume → ≤10 search keywords (also the "complete skill list" the scorer trusts) |
| `services/embeddings.py` | batched embedding calls, 8k-char input cap |
| `services/retrieve.py` | dense + lexical ranking per query, RRF fusion, backfill of posting vectors |
| `services/resume_chunks.py` | resume → sections → embeddings; per-posting context assembly |
| `services/match.py` | MatchJob lifecycle, the scoring prompt, shortlist query |
| `services/pipeline.py` | the weekly run, in order; shared by CLI and HTTP |
| `endpoints/profile.py` | the stored CV: markdown/plain text, or a PDF whose text layer is extracted here |
| `endpoints/pipeline.py` | `POST /pipeline/run`, `GET /pipeline/status`, `GET /shortlist` (paged) |
| `cli/match_pipeline.py` | the weekly entrypoint a cron actually calls |
| `cli/ingest_gmail.py` | the daily mail-only entrypoint |
| `cli/apply.py` | opens a shortlisted offer's form in a real browser, fills it, stops before Submit |

## Where the cost is

Embeddings are rounding-error cheap; the scoring call is not. Two things bound it:
retrieval caps how many postings get scored (`retrieval_top_k`, default 50), and
`build_resume_context` sends 3 resume sections instead of the whole CV.

`match_jobs` rows are never re-scored, so a rerun on the same day costs almost nothing.
