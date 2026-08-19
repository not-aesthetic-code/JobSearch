"""One-off: fill `remote` on eldorado rows ingested before the column existed.

Re-reads each detail page for its schema.org `jobLocationType`. Commits per row,
and only looks at rows where remote IS NULL — so an interrupted run just resumes
where it stopped when you run it again.

Run: uv run python -m cli.backfill_remote
"""

import asyncio

import httpx
from sqlalchemy import select

from jobsearch.database.models import JobPosting
from jobsearch.database.session import get_sessionmaker
from jobsearch.services.ingest_eldorado import _HEADERS, SOURCE, _parse_detail_page


async def main() -> None:
    async with get_sessionmaker()() as session:
        rows = (
            await session.execute(
                select(JobPosting.id, JobPosting.source_id, JobPosting.url).where(
                    JobPosting.source == SOURCE, JobPosting.remote.is_(None)
                )
            )
        ).all()
        print(f"{len(rows)} postings to re-read")

        filled = unreachable = 0
        async with httpx.AsyncClient(headers=_HEADERS, timeout=30.0, follow_redirects=True) as client:
            for done, (posting_id, source_id, url) in enumerate(rows, start=1):
                try:
                    response = await client.get(url)
                except httpx.HTTPError:
                    unreachable += 1
                    continue

                if response.status_code != 200:
                    unreachable += 1  # expired offers 404, and that is fine
                else:
                    parsed = _parse_detail_page(response.text, source_id)
                    if parsed is not None and parsed["remote"] is not None:
                        await session.execute(
                            JobPosting.__table__.update()
                            .where(JobPosting.id == posting_id)
                            .values(remote=parsed["remote"])
                        )
                        await session.commit()
                        filled += 1

                if done % 25 == 0:
                    print(f"  {done}/{len(rows)} — filled {filled}, unreachable {unreachable}")
                await asyncio.sleep(0.3)  # same politeness as the scraper

    print(f"filled {filled}, unreachable {unreachable}, still unknown {len(rows) - filled}")


if __name__ == "__main__":
    asyncio.run(main())
