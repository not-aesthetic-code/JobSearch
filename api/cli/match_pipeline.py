"""Full pipeline: resume -> keywords -> ingest eldorado -> LLM scoring -> shortlist.

Run: uv run python -m cli.match_pipeline path/to/resume.txt
"""

import asyncio
import sys
from pathlib import Path

from jobsearch.config import get_settings
from jobsearch.database.session import get_sessionmaker
from jobsearch.services.match import get_shortlist
from jobsearch.services.pipeline import get_or_create_local_user, run_pipeline


async def main(resume_path: str) -> None:
    resume_text = Path(resume_path).read_text().strip()

    async with get_sessionmaker()() as session:
        summary = await run_pipeline(session, resume_text)
        print(f"Keywords: {', '.join(summary['keywords'])}")
        print(f"Ingested {summary['ingested']} new postings from eldorado")
        print(f"Scored {summary['completed']}/{summary['created']} new match jobs")

        user = await get_or_create_local_user(session)
        shortlist = await get_shortlist(session, user.id)
        print(f"\nShortlist (score >= {get_settings().match_threshold}):\n")
        for score, summary_text, title, company, url, *_ in shortlist:
            print(f"[{score}] {title} — {company or '?'}")
            print(f"      {url}")
            print(f"      {summary_text}\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: uv run python -m cli.match_pipeline path/to/resume.txt")
    asyncio.run(main(sys.argv[1]))
