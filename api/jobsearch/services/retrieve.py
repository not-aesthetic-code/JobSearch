"""Hybrid retrieval over job postings: dense (pgvector cosine) + lexical
(Postgres full-text), fused with Reciprocal Rank Fusion.

Why both: embeddings match meaning ("build REST services" ~ "backend API
development") but blur exact tokens, so an offer demanding Terraform ranks the
same as one demanding Pulumi. Full-text nails the exact token and knows nothing
about meaning. RRF needs no score calibration between the two — it only reads
ranks — which is why it beats hand-tuned weighted sums here."""

import uuid
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jobsearch.config import get_settings
from jobsearch.database.models import JobPosting
from jobsearch.services.embeddings import embed

RRF_K = 60  # standard smoothing constant: rank 1 scores 1/61, rank 2 1/62, ...


def posting_text(title: str, company: str | None, description: str) -> str:
    """The document side of retrieval — must stay in sync between embedding
    writes and any re-embed, or vectors stop being comparable."""
    return f"{title} at {company or 'unknown company'}\n\n{description}"


async def embed_new_postings(session: AsyncSession) -> int:
    """Embed every posting that has no vector yet. Idempotent, so a crashed run
    just resumes: only the missing rows cost anything on the next pass."""
    rows = (
        await session.execute(
            select(JobPosting.id, JobPosting.title, JobPosting.company, JobPosting.description_text).where(
                JobPosting.embedding.is_(None)
            )
        )
    ).all()
    if not rows:
        return 0

    vectors = await embed([posting_text(title, company, description) for _, title, company, description in rows])
    for (posting_id, *_), vector in zip(rows, vectors, strict=True):
        await session.execute(
            JobPosting.__table__.update().where(JobPosting.id == posting_id).values(embedding=vector)
        )
    await session.commit()
    return len(rows)


async def _dense_ranking(session: AsyncSession, query_vector: list[float], top_k: int) -> Sequence[uuid.UUID]:
    return (
        await session.scalars(
            select(JobPosting.id)
            .where(JobPosting.embedding.is_not(None))
            .order_by(JobPosting.embedding.cosine_distance(query_vector))
            .limit(top_k)
        )
    ).all()


async def _lexical_ranking(session: AsyncSession, query: str, top_k: int) -> Sequence[uuid.UUID]:
    # websearch_to_tsquery never raises on arbitrary input, unlike to_tsquery —
    # keywords come from an LLM, so they can contain anything
    tsquery = func.websearch_to_tsquery("english", query)
    return (
        await session.scalars(
            select(JobPosting.id)
            .where(JobPosting.search_vector.op("@@")(tsquery))
            .order_by(func.ts_rank_cd(JobPosting.search_vector, tsquery).desc())
            .limit(top_k)
        )
    ).all()


async def retrieve(session: AsyncSession, queries: Sequence[str], top_k: int | None = None) -> list[uuid.UUID]:
    """Best `top_k` posting ids for a set of queries (resume keywords, or the
    resume itself). Every query contributes a dense and a lexical ranking;
    RRF fuses all of them into one list."""
    if top_k is None:
        top_k = get_settings().retrieval_top_k

    # one batched call for every query's vector, instead of one call per query
    query_vectors = await embed(list(queries))

    scores: dict[uuid.UUID, float] = defaultdict(float)
    for query, query_vector in zip(queries, query_vectors, strict=True):
        for ranking in (
            await _dense_ranking(session, query_vector, top_k),
            await _lexical_ranking(session, query, top_k),
        ):
            for rank, posting_id in enumerate(ranking, start=1):
                scores[posting_id] += 1 / (RRF_K + rank)

    return sorted(scores, key=lambda pid: scores[pid], reverse=True)[:top_k]
