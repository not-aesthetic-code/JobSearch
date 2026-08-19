"""Resume chunking and per-posting context retrieval — the "augmented" half.

A posting is scored against the sections of the CV that answer it, not the whole
document: shorter prompts, and the summary can point at real resume lines.

The obvious failure mode of doing this is the scorer concluding "missing
must-have Rust" when Rust sits in a chunk retrieval didn't return. So the
context always carries the full extracted keyword list alongside the retrieved
sections — complete evidence for "do they know X", retrieved prose for "how
well does this fit"."""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobsearch.config import get_settings
from jobsearch.database.models import JobPosting, Resume, ResumeChunk
from jobsearch.services.embeddings import embed

# a CV section ("Experience — Company X", a bullet block) is usually 200-1500
# chars; below MIN a chunk is a heading with no content, above MAX it stops
# being specific enough to retrieve
MIN_CHARS = 200
MAX_CHARS = 1500
# a CV opens with name, title and summary — the only place total years of
# experience is stated, and the scorer needs it for every posting regardless of
# which sections retrieval picked
HEADER_CHARS = 1200
_BLANK_LINE = re.compile(r"\n\s*\n")


def chunk_text(text: str) -> list[str]:
    """Split on blank lines — a resume already marks its own sections that way —
    then greedily glue runt blocks (bare headings, one-line entries) onto the
    previous chunk and hard-split anything over MAX_CHARS."""
    chunks: list[str] = []
    for block in (b.strip() for b in _BLANK_LINE.split(text)):
        while len(block) > MAX_CHARS:
            cut = block.rfind("\n", 0, MAX_CHARS)  # prefer a line boundary over mid-word
            if cut <= 0:
                cut = MAX_CHARS
            chunks.append(block[:cut].strip())
            block = block[cut:].strip()
        if not block:
            continue
        if chunks and len(chunks[-1]) < MIN_CHARS and len(chunks[-1]) + len(block) <= MAX_CHARS:
            chunks[-1] = f"{chunks[-1]}\n\n{block}"
        else:
            chunks.append(block)
    return chunks


async def ensure_resume_chunks(session: AsyncSession, resume: Resume) -> int:
    """Chunk and embed the resume once. Returns the number of chunks created —
    0 when they already exist, since a Resume row's raw_text never changes
    (a new version is a new row)."""
    existing = await session.scalar(
        select(ResumeChunk.id).where(ResumeChunk.resume_id == resume.id).limit(1)
    )
    if existing is not None:
        return 0

    texts = chunk_text(resume.raw_text)
    vectors = await embed(texts)
    session.add_all(
        ResumeChunk(resume_id=resume.id, chunk_index=index, text=text, embedding=vector)
        for index, (text, vector) in enumerate(zip(texts, vectors, strict=True))
    )
    await session.commit()
    return len(texts)


async def build_resume_context(session: AsyncSession, resume: Resume, posting: JobPosting) -> str:
    """The resume side of the scoring prompt for one posting: full keyword list
    plus the resume sections closest to that posting.

    Reuses the posting's own embedding as the query, so retrieving context costs
    no extra embedding calls. Falls back to the whole resume if the posting never
    got embedded — a wrong score is worse than a long prompt."""
    if posting.embedding is None:
        return resume.raw_text

    sections = (
        await session.scalars(
            select(ResumeChunk.text)
            .where(ResumeChunk.resume_id == resume.id)
            .order_by(ResumeChunk.embedding.cosine_distance(posting.embedding))
            .limit(get_settings().resume_context_chunks)
        )
    ).all()
    if not sections:
        return resume.raw_text

    return _format_context(resume, sections)


def _format_context(resume: Resume, sections: list[str]) -> str:
    """Header and skill list are unconditional; only the sections are retrieved.
    Both exist because the scorer reasons about the candidate *globally* — total
    years, seniority, whether a technology is absent — and a partial CV makes it
    confidently wrong about all three."""
    return (
        f"RESUME HEADER (name, title, years of experience):\n{resume.raw_text[:HEADER_CHARS]}\n\n"
        f"COMPLETE SKILL LIST: {', '.join(resume.keywords or [])}\n\n"
        "MOST RELEVANT RESUME SECTIONS:\n\n" + "\n\n---\n\n".join(sections)
    )
