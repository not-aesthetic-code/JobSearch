"""One generic scraper, many boards. A board is a config row, not a module.

The trick is that almost every job board embeds a schema.org JobPosting blob on
its detail pages — Google for Jobs requires it, so any board that wants to be
found has one. That makes the *detail* half identical everywhere; the only
board-specific knowledge left is "what URL do I search, and which links on the
result page are offers". Both fit in a JSON file, so adding a board needs no code.

Boards that render results with JS, sit behind a login, or ship no JSON-LD do
not fit here — those still need their own module (see ingest_eldorado) or the
Gmail alert route.
"""

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobsearch.database.models import JobPosting
from jobsearch.database.operations.job_posting import upsert_job_postings

BOARDS_PATH = Path("boards.json")
_HEADERS = {"User-Agent": "jobsearch (personal project)"}


class BoardConfig(BaseModel):
    """What one board needs. Everything else is the same for all of them."""

    name: str  # becomes JobPosting.source — changing it re-ingests the board as new
    search_url: str  # template: {keyword} required, {page} optional
    link_selector: str  # CSS selector matching offer links (or their containers)
    # optional regex over the offer path; group 1 becomes source_id. Without it the
    # path itself is the id, which is stable on every board that uses slugs
    id_pattern: str | None = None
    max_pages: int = Field(default=2, ge=1, le=20)
    delay_seconds: float = Field(default=0.3, ge=0)
    enabled: bool = True


def load_boards(path: Path = BOARDS_PATH) -> list[BoardConfig]:
    """User-supplied boards. Missing file = none, which is the default state."""
    if not path.exists():
        return []
    return [board for board in (BoardConfig(**raw) for raw in json.loads(path.read_text())) if board.enabled]


def parse_links(html: str, base_url: str, config: BoardConfig) -> dict[str, str]:
    """Result page -> {source_id: absolute offer url}."""
    soup = BeautifulSoup(html, "lxml")
    pattern = re.compile(config.id_pattern) if config.id_pattern else None
    found: dict[str, str] = {}
    for element in soup.select(config.link_selector):
        link = element if element.name == "a" else element.find("a", href=True)
        if link is None or not link.get("href"):
            continue
        url = urljoin(base_url, link["href"])
        path = urlsplit(url).path  # drop ?utm/?ctx tracking, or every rerun looks new
        if pattern is None:
            found[path] = url
            continue
        match = pattern.search(path)
        if match:
            found[match.group(1)] = url
    return found


def parse_jsonld_posting(html: str, source: str, source_id: str, url: str) -> dict[str, Any] | None:
    """Detail page -> job_postings row, from the embedded schema.org blob.
    Structured fields come from the JSON-LD; description_text from the rendered
    page body, which holds the tech stack the blob usually omits."""
    soup = BeautifulSoup(html, "lxml")
    data = None
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        # some boards wrap everything in an @graph list instead of a bare object
        for candidate in payload if isinstance(payload, list) else [payload]:
            if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                data = candidate
                break
        if data:
            break
    if data is None:
        return None

    main = soup.find("main")
    description = main.get_text(" ", strip=True) if main else data.get("description", "")

    locations = data.get("jobLocation") or []
    locations = locations if isinstance(locations, list) else [locations]
    locality = locations[0].get("address", {}).get("addressLocality") if locations else None

    posted_at = None
    if data.get("datePosted"):
        try:
            posted_at = datetime.fromisoformat(data["datePosted"]).replace(tzinfo=UTC)
        except ValueError:  # boards emit plenty of non-ISO dates; the field is optional
            posted_at = None

    return {
        "source": source,
        "source_id": source_id,
        "title": data.get("title") or "Untitled",
        "company": (data.get("hiringOrganization") or {}).get("name"),
        "location": locality,
        "url": data.get("url") or url,
        "description_text": description,
        # schema.org marks remote roles TELECOMMUTE and gives on-site ones a
        # jobLocation instead; neither present means the page simply didn't say
        "remote": True if data.get("jobLocationType") == "TELECOMMUTE" else (False if locations else None),
        "posted_at": posted_at,
    }


async def collect_offers(client: httpx.AsyncClient, config: BoardConfig, keywords: list[str]) -> dict[str, str]:
    """Every offer link the board returns for these keywords."""
    offers: dict[str, str] = {}
    paged = "{page}" in config.search_url
    for keyword in keywords:
        for page in range(1, (config.max_pages if paged else 1) + 1):
            url = config.search_url.format(keyword=keyword, page=page)
            response = await client.get(url)
            if response.status_code != 200:
                break
            page_offers = parse_links(response.text, url, config)
            if not page_offers:
                break
            offers.update(page_offers)
            await asyncio.sleep(config.delay_seconds)
    return offers


async def ingest_board(session: AsyncSession, config: BoardConfig, keywords: list[str]) -> int:
    """Search, fetch the detail pages we haven't seen, upsert. New postings only —
    a rerun skips everything already stored, so it costs one search per keyword."""
    async with httpx.AsyncClient(headers=_HEADERS, timeout=30.0, follow_redirects=True) as client:
        offers = await collect_offers(client, config, keywords)
        if not offers:
            return 0

        known = set(
            await session.scalars(
                select(JobPosting.source_id).where(
                    JobPosting.source == config.name, JobPosting.source_id.in_(offers)
                )
            )
        )

        rows = []
        for source_id in set(offers) - known:
            response = await client.get(offers[source_id])
            if response.status_code == 200:
                row = parse_jsonld_posting(response.text, config.name, source_id, offers[source_id])
                if row is not None:
                    rows.append(row)
            await asyncio.sleep(config.delay_seconds)

    return await upsert_job_postings(session, rows)


async def ingest_boards(session: AsyncSession, keywords: list[str], path: Path = BOARDS_PATH) -> int:
    """All configured boards. One board failing must not lose the others' rows."""
    total = 0
    for config in load_boards(path):
        try:
            total += await ingest_board(session, config, keywords)
        except Exception as error:  # a board changing its markup is routine, not fatal
            print(f"board {config.name} failed: {error}")
    return total
