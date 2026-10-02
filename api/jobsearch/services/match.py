"""Scores job postings against a resume via the MatchJob/MatchOutput lifecycle."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jobsearch.config import get_settings
from jobsearch.database.models import JobPosting, MatchJob, MatchOutput, Resume
from jobsearch.database.models.match_output import Seniority
from jobsearch.services.llm import get_openai_client
from jobsearch.services.resume_chunks import build_resume_context

_SYSTEM_PROMPT = (
    "You score how well a candidate's resume fits a job posting, 0-100. "
    "0 = completely unrelated field, 100 = perfect fit on skills, seniority and role. "
    "Be strict: missing must-have technologies or a clear seniority mismatch should "
    "push the score below 50. Summarize the reasoning in 2-3 sentences, quoting the "
    "resume phrase you relied on.\n"
    "The RESUME block gives the candidate's header, complete skill list, and the "
    "resume sections most relevant to this posting. Treat the header's years of "
    "experience and the skill list as exhaustive and authoritative. Never infer a "
    "gap — in tenure, seniority or skills — from a section not being shown: only "
    "the relevant sections are included, so the roles listed are not the full "
    "career history.\n"
    "Also classify the level the posting asks for as junior, mid or senior — from the "
    "title and required experience, regardless of the candidate."
)


class MatchScore(BaseModel):
    score: int = Field(ge=0, le=100)
    summary: str
    seniority: Seniority


async def _score(resume_context: str, posting: JobPosting) -> MatchScore:
    job_text = f"{posting.title} at {posting.company or 'unknown company'}\n\n{posting.description_text}"
    response = await get_openai_client().chat.completions.parse(
        model=get_settings().openai_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"RESUME:\n{resume_context}\n\nJOB POSTING:\n{job_text}"},
        ],
        response_format=MatchScore,
    )
    return response.choices[0].message.parsed


async def create_match_jobs(session: AsyncSession, user_id: uuid.UUID, retrieved_ids: Sequence[uuid.UUID]) -> int:
    """One pending MatchJob per retrieved posting the user doesn't already have
    a job for. Retrieval is what keeps LLM cost bounded — only the top-k
    postings ever reach the scorer."""
    if not retrieved_ids:
        return 0

    already_matched = set(
        (
            await session.scalars(
                select(MatchJob.job_posting_id).where(
                    MatchJob.user_id == user_id, MatchJob.job_posting_id.in_(retrieved_ids)
                )
            )
        ).all()
    )
    new_ids = [pid for pid in retrieved_ids if pid not in already_matched]
    session.add_all(MatchJob(user_id=user_id, job_posting_id=pid) for pid in new_ids)
    await session.commit()
    return len(new_ids)


async def process_match_jobs(session: AsyncSession, user_id: uuid.UUID, resume: Resume) -> int:
    """Run every pending MatchJob for the user. Commits per job so a crash
    mid-run loses at most one result.
    ponytail: sequential — parallelize with a semaphore if runs get too slow."""
    jobs = (
        await session.scalars(
            select(MatchJob).where(MatchJob.user_id == user_id, MatchJob.status == "pending")
        )
    ).all()

    completed = 0
    for job in jobs:
        job.status = "processing"
        job.started_at = datetime.now(UTC)
        job.attempt_count += 1
        await session.commit()

        posting = await session.get(JobPosting, job.job_posting_id)
        try:
            result = await _score(await build_resume_context(session, resume, posting), posting)
            session.add(MatchOutput(match_job_id=job.id, score=result.score, summary=result.summary, seniority=result.seniority))
            job.status = "completed"
            completed += 1
        except Exception as exc:  # noqa: BLE001 — one bad posting must not kill the run
            job.status = "failed"
            job.error_code = type(exc).__name__
            job.error_message = str(exc)[:2000]
        job.finished_at = datetime.now(UTC)
        await session.commit()
    return completed


SortKey = Literal["score", "newest", "added"]

# every sort ends on JobPosting.id: without a unique tiebreaker, rows that tie on
# the leading column can swap between pages, so paging repeats one and skips another
_SORTS = {
    "score": (MatchOutput.score.desc(), JobPosting.id),
    "newest": (JobPosting.posted_at.desc().nullslast(), JobPosting.id),  # when the employer published
    "added": (JobPosting.scraped_at.desc(), JobPosting.id),  # when we first saw it
}


def _shortlist_scope(stmt, user_id: uuid.UUID, min_score: int | None, remote: bool | None, junior: bool):
    """The joins and filters both the page query and the count query need — kept
    in one place so a paged total can never disagree with the page itself."""
    if min_score is None:
        min_score = get_settings().match_threshold
    stmt = (
        stmt.join(MatchJob, MatchOutput.match_job_id == MatchJob.id)
        .join(JobPosting, MatchJob.job_posting_id == JobPosting.id)
        .where(MatchJob.user_id == user_id, MatchOutput.score >= min_score, MatchJob.dismissed_at.is_(None), JobPosting.url != "")  # gmail alerts stored no link — nothing to open or apply to
    )
    if remote is not None:
        # NULL is "the source never said" — it belongs to neither side, so an
        # explicit filter excludes it rather than guessing
        stmt = stmt.where(JobPosting.remote.is_(remote))
    if not junior:  # junior is opt-in; NULL (scored before the column) stays visible
        stmt = stmt.where(MatchOutput.seniority.is_distinct_from("junior"))
    return stmt


async def get_shortlist(
    session: AsyncSession,
    user_id: uuid.UUID,
    min_score: int | None = None,
    limit: int | None = None,
    offset: int = 0,
    sort: SortKey = "score",
    remote: bool | None = None,
    junior: bool = False,
):
    """Completed matches at or above the threshold. `limit=None` returns
    everything — that's what the CLI indexes into by position."""
    stmt = _shortlist_scope(
        select(
            MatchOutput.score,
            MatchOutput.summary,
            JobPosting.title,
            JobPosting.company,
            JobPosting.url,
            JobPosting.remote,
            JobPosting.location,
            JobPosting.posted_at,
            MatchJob.id,
            MatchJob.seen_at,
            MatchJob.applied_at,
            MatchOutput.seniority,
        ),
        user_id,
        min_score,
        remote,
        junior,
    ).order_by(*_SORTS[sort])
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    return (await session.execute(stmt)).all()


async def count_shortlist(
    session: AsyncSession, user_id: uuid.UUID, min_score: int | None = None, remote: bool | None = None, junior: bool = False
) -> int:
    # select_from is required: func.count() alone gives the join no left-hand table
    stmt = _shortlist_scope(select(func.count()).select_from(MatchOutput), user_id, min_score, remote, junior)
    return await session.scalar(stmt) or 0


MatchMark = Literal["seen", "applied", "dismissed"]


async def mark_match(session: AsyncSession, user_id: uuid.UUID, match_id: uuid.UUID, mark: MatchMark) -> bool:
    """Stamp seen/applied/dismissed on one of the user's matches. False = not theirs / not found."""
    match = await session.scalar(select(MatchJob).where(MatchJob.id == match_id, MatchJob.user_id == user_id))
    if match is None:
        return False
    setattr(match, f"{mark}_at", func.now())
    await session.commit()
    return True
