# jobSearch

Personal job-hunting pipeline. Pulls postings from a few sources, ranks them
against your resume with hybrid retrieval, has an LLM score the survivors, and
gives you a shortlist. Then it opens the application form in a real browser and
fills it in — and stops before Submit.

One user, one weekly run. See [docs/architecture.md](docs/architecture.md) for
the flow and [docs/adr](docs/adr) for the decisions that shaped it.

## Run it

```bash
docker compose -f api/docker-compose.yml up -d       # postgres + pgvector on :5434

cd api
cp .env.example .env                                 # set OPENAI_API_KEY at minimum
uv sync
uv run alembic upgrade head
uv run uvicorn jobsearch.app:app --port 8000

cd ../web
cp .env.example .env.local                           # API_URL must match the port above
npm install
npm run dev                                          # http://localhost:3000
```

Save your CV once on **/profile** — paste it as markdown or upload a PDF — then
hit **Find offers** on the home page, watch the job counters, and sort or filter
the shortlist (best match / newest / recently added, remote / on-site). Runs take
a few minutes — scraping and scoring dominate.

Tests: `cd api && uv run pytest` (24 tests, no network, no DB).

## What it can do today

**Ingest** — three sources, all upserting on `(source, source_id)` so reruns
refresh rather than duplicate:

- `czyjesteldorado` — search + detail scrape, driven by your resume keywords. In the pipeline.
- **Any board you add yourself** — `boards.json`, no code. See *Adding a board* below.
- Gmail job alerts — IMAP read of configured senders, LLM extraction per mail, mail moved to Trash once stored. In the pipeline, no-op unless `GMAIL_SENDERS` is set.
- RemoteOK — free JSON feed. **CLI only**, not wired into `run_pipeline`; run `python -m cli.ingest_remoteok` to top up the pool.

**Retrieval** — dense (pgvector cosine) + lexical (`websearch_to_tsquery`) per
query, fused with RRF, top 25. Queries are your extracted keywords *plus* the
full resume text, so good fits with unfamiliar wording still surface.

**Scoring** — one LLM call per retrieved posting, given only the top-3 relevant
resume sections plus the full keyword list. Returns 0-100 and a summary that
quotes your resume. Scored jobs are never re-scored, so a rerun costs almost
nothing.

**Shortlist** — everything at or above `match_threshold` (default 60), best
first. Visible in the web UI, `GET /shortlist`, or the CLI.

**Apply** — `python -m cli.apply <position>` opens the offer in a persistent
Chromium profile (ATS logins survive between runs), follows the apply link, and
fills the form in two passes: a keyword table handles the fields every form has
(EN + PL labels), then **one LLM call answers the rest** — dropdowns, radio
groups, "why do you want to work here" — grounded in `profile.json` plus your
stored resume. Each answer carries a confidence; anything under
`--min-confidence` (0.7) is left blank and reported instead of guessed. Walks
multi-step wizards by clicking Next, screenshotting each step.

By default it stops before Submit and before any consent box, and hands you the
window. `--submit` ticks the required consents and clicks Submit — but refuses
if any field came out blank, and gives you 8s to Ctrl-C.

## Entry points

| | |
| --- | --- |
| `web` | Next.js 16 UI. Server routes proxy to the API so the key stays server-side. |
| `GET/PUT /profile/resume` | The stored CV, as markdown or plain text. Same text = same row, so keywords are extracted once. |
| `PUT /profile/resume/pdf` | Raw `application/pdf` body; the text layer becomes the stored CV. Scans are rejected — no OCR. |
| `POST /pipeline/run` | Starts a run in the background. Omit `resume_text` to use the stored CV. Omit `sources` to ingest from all of them (`[]` skips ingest, just re-retrieves/re-scores). 409 if one is already going. |
| `POST /pipeline/stop` | Cancels the in-flight run. 409 if none is running. |
| `GET /pipeline/status` | `running`, current `phase`, per-source ingest `progress`, job counts by status, last error. |
| `GET /shortlist?limit&offset&sort&remote` | Scored matches above threshold, paged: `{items, total}`. `sort` = `score`\|`newest`\|`added`; `remote` omitted = any. |
| `cli.backfill_remote` | One-off: re-read eldorado detail pages to fill `remote` on rows ingested before the column existed. |
| `cli.match_pipeline <resume.txt>` | The weekly run a cron calls. |
| `cli.ingest_gmail` | Daily mail-only ingest. |
| `cli.ingest_remoteok` | Top up the posting pool from RemoteOK. |
| `cli.add_board` | Probe a new board's selector, then save it to `boards.json`. |
| `cli.apply <n> [--submit] [--min-confidence 0.7]` | Prepare (or send) application #n. |

## Adding a board

Most boards need no code. Their detail pages carry a schema.org `JobPosting`
blob — Google for Jobs requires it, so any board that wants to be found has one
— which makes the hard half identical everywhere. All that's board-specific is
the search URL and which links on the results page are offers.

Work the selector out once (Inspect an offer title; prefer an href filter like
`a[href*='/offers/']` over class names, which are generated and change on every
deploy), then probe it before trusting it:

```bash
cd api
uv run python -m cli.add_board \
  --name justjoin \
  --search-url "https://justjoin.it/job-offers/all-locations/{keyword}?page={page}" \
  --link-selector "a[href*='/offers/']" \
  --keyword react            # add --save once the output looks right
```

It fetches one search page, prints the offer links it matched, fetches the first
one and shows the exact row it would store. Nothing is written without `--save`,
so a wrong selector costs one request rather than a database full of nav links.
Saved boards join every pipeline run; set `"enabled": false` in `boards.json` to
park one without deleting it.

Where it stops: boards that render results with JavaScript, sit behind a login,
or ship no JSON-LD. `add_board` tells you which of those you hit. Those need
their own module (`ingest_eldorado.py` is the template) — or just point a Gmail
job alert at the account and let `ingest_gmail` extract them.

## Config

All of it in `api/.env` (see `.env.example`). Worth knowing:

- `OPENAI_BASE_URL` — any OpenAI-compatible endpoint (OpenRouter, Ollama, Groq). Empty = OpenAI.
- `API_KEY` — single static bearer key checked on every route. Empty = auth off, local only. Must match `API_KEY` in `web/.env.local`.
- `retrieval_top_k` (25) and `resume_context_chunks` (3) — the two knobs that bound LLM cost.
- `match_threshold` (60) — shortlist cutoff.
- `GMAIL_AFTER_INGEST` — `trash` (30-day recovery) or `keep` (mark read only).

## Known edges

- Run state (`_running`, `_last_error`) lives in process memory — single worker only.
- `cli.apply` needs a `profile.json` in `api/` and a CV path; it tells you the shape if it's missing.
- Answers are only as good as `profile.json` — the prompt forbids inventing dates,
  salary or visa status, so a fact you never wrote down comes back blank.
- Custom widgets (React comboboxes, Workday's own controls) that aren't real
  `<input>`/`<select>` elements are invisible to the scraper.
