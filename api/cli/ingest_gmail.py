"""Daily job-alert mail ingest — the piece a cron runs every morning.

Run: uv run python -m cli.ingest_gmail
"""

import asyncio

from jobsearch.config import get_settings
from jobsearch.database.session import get_sessionmaker
from jobsearch.services.ingest_gmail import ingest_gmail


async def main() -> None:
    settings = get_settings()
    async with get_sessionmaker()() as session:
        stored = await ingest_gmail(session)
    fate = "moved to Trash" if settings.gmail_after_ingest == "trash" else "marked read"
    print(f"Stored {stored} postings from mail; processed mails {fate}.")


if __name__ == "__main__":
    asyncio.run(main())
