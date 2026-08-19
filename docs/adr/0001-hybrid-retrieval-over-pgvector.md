# ADR 0001 — Hybrid retrieval over pgvector, no vector database, no RAG framework

- **Status:** Accepted
- **Date:** 2026-08-12
- **Supersedes:** the `ILIKE '%keyword%'` prefilter in `create_match_jobs`

## Context

Every posting scored costs one LLM call, so something has to choose which of a
few thousand postings deserve one. That chooser was a keyword `ILIKE` filter over
title and description. It fails in both directions: a posting saying "build REST
services in Python" misses the keyword `fastapi` and never gets scored, while a
posting mentioning `python` once in a list of nice-to-haves does.

Scale is one user, a weekly run, low thousands of postings — small enough that
almost any approach performs adequately, which makes operational cost the
deciding factor rather than latency.

## Decision

Retrieve with two channels and fuse them:

1. **Dense** — `text-embedding-3-small` (1536d) over `title + company + description`,
   cosine distance via pgvector, HNSW index.
2. **Lexical** — a Postgres generated `tsvector` column, queried with
   `websearch_to_tsquery` and ranked by `ts_rank_cd`.

Each query (every extracted keyword, plus the full resume text) produces one
ranking per channel; all rankings are fused with **Reciprocal Rank Fusion**
(`1 / (60 + rank)`), and the top `retrieval_top_k` postings become MatchJobs.

Generation is augmented the same way: each posting retrieves its 3 nearest
resume sections from `resume_chunks`, reusing the posting's own embedding as the
query vector, and the scorer sees those instead of the whole CV.

Vectors live in the Postgres instance the app already runs. No vector database,
no LangChain/LlamaIndex.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Dedicated vector DB (Qdrant, Chroma, Pinecone) | A second datastore to run, back up and keep in sync with `job_postings`, for a table in the thousands. pgvector gives transactional consistency with the rows themselves and one less service in the weekly cron. |
| Dense retrieval only | Embeddings blur exact tokens: an offer requiring Terraform ranks alongside one requiring Pulumi. Exact technology names are precisely what matters in a job filter. |
| Weighted score blend instead of RRF | Cosine distance and `ts_rank_cd` are on unrelated scales, so the weights need recalibrating whenever either side changes. RRF reads ranks only, so there is nothing to tune. |
| LangChain / LlamaIndex | Their value is swappable stores and pre-built chains. There is one store, one chain, and it is ~120 lines of SQLAlchemy. The abstraction would be larger than the code it wraps. |
| Keep `ILIKE`, just tune keywords | Cheapest option, and the recall problem is structural: no keyword list covers paraphrase. |

## Consequences

- Postings need an embedding before they are retrievable. `embed_new_postings` is
  idempotent, so a crashed run re-embeds only what is missing.
- `search_vector` is generated and persisted by Postgres, so it cannot drift from
  the description; the tradeoff is a rewrite of the column on every posting upsert.
- Changing `embedding_model` invalidates every stored vector on both sides —
  postings and resume chunks must be re-embedded together, or cross-comparisons
  become meaningless.
- **Known failure mode, observed on the first live run:** partial context makes the
  scorer confidently wrong about *global* properties of the candidate. A senior
  full-stack posting scored **44** with the reasoning "the visible roles cover only
  ~2 years" — retrieval had returned two of four employment sections, so the model
  counted tenure from what it could see. The same posting scores **92** once the
  context carries the resume header.

  The context therefore has three parts, and only one of them is retrieved:
  the **header** (name, title, total years — unconditional), the **complete skill
  list** (unconditional), and the **top-k retrieved sections**. Skills answer "does
  the candidate know X", the header answers "how senior are they", and retrieval
  only supplies the prose evidence for "how well does this fit".
- On a two-page CV the token saving from retrieving sections is modest — 3.8k chars
  of context against 6.3k for the whole document. Chunk retrieval earns its place
  here as the pattern that scales to long documents and many candidates, not as a
  cost optimisation at this size.
- The HNSW and GIN indexes do nothing at this table size — Postgres will seq-scan
  either way. They exist so the query plan doesn't change shape if the corpus grows.
- **Not yet measured.** The recall claim above is reasoned, not benchmarked. An
  eval harness (recall@k for hybrid vs dense-only vs `ILIKE`) needs hand-labeled
  query→posting pairs; labels derived from existing `match_outputs` scores would
  only cover postings retrieval already surfaced, and would be circular.
