"""Pulls postings from RemoteOK's free JSON API — no scraping, no auth, no
rate-limit concerns for a once-a-day pull. Reusing deckard's crawl4ai-based
scraper is worth it for a specific company's careers page, not for a feed
that already hands us structured JSON."""

import html
import re
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from jobsearch.database.operations.job_posting import upsert_job_postings

REMOTEOK_API_URL = "https://remoteok.com/api"
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(raw: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", raw)).strip()


def _to_job_posting_row(item: dict[str, Any]) -> dict[str, Any] | None:
    if "id" not in item:  # first item in the feed is a legal notice, not a job
        return None
    return {
        "source": "remoteok",
        "source_id": str(item["id"]),
        "title": item.get("position") or "Untitled",
        "company": item.get("company"),
        "location": item.get("location") or None,
        "url": item.get("url") or item.get("apply_url"),
        "description_text": _strip_html(item.get("description") or ""),
        "remote": True,  # it's RemoteOK — the whole board is remote by definition
        "posted_at": datetime.fromisoformat(item["date"]) if item.get("date") else None,
    }


async def fetch_remoteok_postings() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(headers={"User-Agent": "jobsearch (personal project)"}) as client:
        response = await client.get(REMOTEOK_API_URL, timeout=30.0)
        response.raise_for_status()
        items: list[dict[str, Any]] = response.json()

    rows = (_to_job_posting_row(item) for item in items)
    return [row for row in rows if row is not None]


async def ingest_remoteok(session: AsyncSession) -> int:
    rows = await fetch_remoteok_postings()
    return await upsert_job_postings(session, rows)
