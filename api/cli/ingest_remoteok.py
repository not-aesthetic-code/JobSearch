"""Run: uv run python -m cli.ingest_remoteok"""

import asyncio

from jobsearch.database.session import get_sessionmaker
from jobsearch.services.ingest_remoteok import ingest_remoteok


async def main() -> None:
    async with get_sessionmaker()() as session:
        count = await ingest_remoteok(session)
    print(f"Upserted {count} job postings from RemoteOK")


if __name__ == "__main__":
    asyncio.run(main())
