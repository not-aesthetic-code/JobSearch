"""Pulls postings from czyjesteldorado.pl by keyword search. The site has no
API, but search results and detail pages are fully server-rendered, and every
detail page embeds a schema.org JobPosting JSON-LD blob — so plain httpx +
BeautifulSoup is enough, no headless browser."""

import asyncio
import re
from typing import Any
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobsearch.database.models import JobPosting
from jobsearch.database.operations.job_posting import upsert_job_postings
from jobsearch.services.ingest_board import parse_jsonld_posting

BASE_URL = "https://czyjesteldorado.pl"
SOURCE = "eldorado"
_HEADERS = {"User-Agent": "jobsearch (personal project)"}
# offer detail paths look like /praca/261752-senior-react-native-developer-...;
# other /praca/ links (e.g. /praca/firma/allegro) are not offers
_OFFER_PATH_RE = re.compile(r"^/praca/(\d+)-")


def _parse_search_page(html: str) -> dict[str, str]:
    """Offer cards on /search?q=... -> {offer_id: detail_path}."""
    soup = BeautifulSoup(html, "lxml")
    paths: dict[str, str] = {}
    for card in soup.select("[data-offer-id]"):
        link = card.find("a", href=True)
        if link is None:
            continue
        path = urlsplit(link["href"]).path  # drop the ?ctx tracking blob
        match = _OFFER_PATH_RE.match(path)
        if match:
            paths[match.group(1)] = path
    return paths


def _parse_detail_page(html: str, offer_id: str) -> dict[str, Any] | None:
    """Detail page -> job_postings row. Nothing eldorado-specific left here —
    its detail pages carry ordinary schema.org JSON-LD, same as every board in
    boards.json."""
    return parse_jsonld_posting(html, SOURCE, offer_id, f"{BASE_URL}/praca/{offer_id}")


async def ingest_eldorado(session: AsyncSession, keywords: list[str], max_pages: int = 2) -> int:
    """Search each keyword, fetch detail pages for offers we haven't seen yet,
    upsert. Returns the number of new postings."""
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=_HEADERS, timeout=30.0, follow_redirects=True
    ) as client:
        paths: dict[str, str] = {}
        for keyword in keywords:
            for page in range(1, max_pages + 1):
                response = await client.get("/search", params={"q": keyword, "page": page})
                response.raise_for_status()
                page_paths = _parse_search_page(response.text)
                if not page_paths:
                    break
                paths.update(page_paths)

        known = set(
            await session.scalars(
                select(JobPosting.source_id).where(
                    JobPosting.source == SOURCE, JobPosting.source_id.in_(paths)
                )
            )
        )

        rows = []
        for offer_id in set(paths) - known:
            response = await client.get(paths[offer_id])
            if response.status_code != 200:
                continue
            row = _parse_detail_page(response.text, offer_id)
            if row is not None:
                rows.append(row)
            await asyncio.sleep(0.3)  # be polite, it's a free site

    return await upsert_job_postings(session, rows)
