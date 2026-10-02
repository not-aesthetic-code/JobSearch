"""The full resume -> keywords -> ingest -> score flow, shared by the CLI and
the HTTP API. Single-user for now: everything hangs off the 'local' user."""

import uuid
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobsearch.database.models import Resume, User
from jobsearch.services.extract_keywords import extract_keywords
from jobsearch.services.ingest_board import ingest_boards
from jobsearch.services.ingest_eldorado import ingest_eldorado
from jobsearch.services.ingest_gmail import ingest_gmail
from jobsearch.services.match import create_match_jobs, process_match_jobs
from jobsearch.services.resume_chunks import ensure_resume_chunks
from jobsearch.services.retrieve import embed_new_postings, retrieve

LOCAL_CLIENT_IDENTIFIER = "local"

# ordered so the frontend can render a stepper without knowing pipeline internals
PHASES = ["ingest", "embed", "retrieve", "score", "done"]

# every source run_pipeline knows how to ingest from — omitting `sources` runs all of them
SOURCES = ["eldorado", "boards"]  # ponytail: "gmail" disabled for now (slow, LLM call per mail); re-add to enable


async def get_or_create_local_user(session: AsyncSession) -> User:
    user = await session.scalar(select(User).where(User.client_identifier == LOCAL_CLIENT_IDENTIFIER))
    if user is None:
        user = User(client_identifier=LOCAL_CLIENT_IDENTIFIER)
        session.add(user)
        await session.commit()
    return user


async def get_latest_resume(session: AsyncSession, user_id: uuid.UUID) -> Resume | None:
    """The profile resume the pipeline matches against."""
    return await session.scalar(
        select(Resume).where(Resume.user_id == user_id).order_by(Resume.created_at.desc()).limit(1)
    )


async def upsert_resume(session: AsyncSession, user_id: uuid.UUID, raw_text: str) -> Resume:
    """Identical text reuses the existing row, so keywords and chunks are
    extracted once no matter how often the profile is re-saved."""
    resume = await session.scalar(
        select(Resume)
        .where(Resume.user_id == user_id, Resume.raw_text == raw_text)
        .order_by(Resume.created_at.desc())
        .limit(1)
    )
    if resume is None:
        resume = Resume(user_id=user_id, raw_text=raw_text)
        session.add(resume)
        await session.commit()
    return resume


async def run_pipeline(
    session: AsyncSession,
    resume_text: str,
    on_phase: Callable[[str], None] | None = None,
    on_progress: Callable[[str, int, int], None] | None = None,
    sources: set[str] | None = None,
) -> dict[str, object]:
    """`sources` restricts which ingest sources run this pass — the retrieve/score
    steps still run over whatever is already in job_postings either way, so an
    empty set is a valid "just re-score what's already ingested" mode."""
    active = SOURCES if sources is None else sources

    def phase(name: str) -> None:
        if on_phase:
            on_phase(name)

    def progress(source: str, done: int, total: int) -> None:
        if on_progress:
            on_progress(source, done, total)

    user = await get_or_create_local_user(session)
    resume = await upsert_resume(session, user.id, resume_text)

    if not resume.keywords:
        resume.keywords = await extract_keywords(resume_text)
        await session.commit()

    chunks = await ensure_resume_chunks(session, resume)

    phase("ingest")
    ingested = 0
    from_mail = 0
    if "eldorado" in active:
        ingested += await ingest_eldorado(
            session, resume.keywords, on_progress=lambda done, total: progress("eldorado", done, total)
        )
    if "boards" in active:
        ingested += await ingest_boards(session, resume.keywords)  # no-op without boards.json
    if "gmail" in active:
        from_mail = await ingest_gmail(  # no-op unless GMAIL_SENDERS is configured
            session, on_progress=lambda done, total: progress("gmail", done, total)
        )

    phase("embed")
    embedded = await embed_new_postings(session)

    phase("retrieve")
    # the resume itself is a query too: it catches good fits whose wording
    # matches none of the extracted keywords
    retrieved_ids = await retrieve(session, [*resume.keywords, resume_text])
    created = await create_match_jobs(session, user.id, retrieved_ids)

    phase("score")
    completed = await process_match_jobs(session, user.id, resume)

    phase("done")
    return {
        "keywords": resume.keywords,
        "chunks": chunks,
        "ingested": ingested,
        "from_mail": from_mail,
        "embedded": embedded,
        "retrieved": len(retrieved_ids),
        "created": created,
        "completed": completed,
    }
