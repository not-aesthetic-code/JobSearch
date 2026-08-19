from collections.abc import Sequence
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jobsearch.database.models import JobPosting


async def upsert_job_postings(session: AsyncSession, postings: Sequence[dict[str, Any]]) -> int:
    """Insert postings, updating in place on `(source, source_id)` conflict —
    reruns of the same ingestion source refresh rows instead of duplicating them."""
    if not postings:
        return 0

    stmt = insert(JobPosting).values(list(postings))
    update_columns = {
        col: stmt.excluded[col]
        for col in ("title", "company", "location", "url", "description_text", "remote", "posted_at")
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=[JobPosting.source, JobPosting.source_id],
        set_=update_columns,
    )
    await session.execute(stmt)
    await session.commit()
    return len(postings)
