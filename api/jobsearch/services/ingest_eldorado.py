"""Pulls postings from czyjesteldorado.pl by keyword search. The site has no
API, but search results and detail pages are fully server-rendered, and every
detail page embeds a schema.org JobPosting JSON-LD blob — so plain httpx +
BeautifulSoup is enough, no headless browser."""

import asyncio
import json
import re
import time
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobsearch.database.models import JobPosting
from jobsearch.database.operations.job_posting import upsert_job_postings
from jobsearch.services.ingest_board import HEADERS, parse_jsonld_posting

BASE_URL = "https://czyjesteldorado.pl"
SOURCE = "eldorado"
CONCURRENCY = 16  # ponytail: lower if the site starts 429ing
MCP_URL = f"{BASE_URL}/_mcp"
SEARCH_TTL = 900  # seconds; reruns within this window skip the search round-trips
_search_cache: dict[tuple[str, ...], tuple[float, dict[str, str]]] = {}  # ponytail: per-process, lost on restart
MAX_NEW_PER_RUN = 40  # most relevant first; reruns work through the rest
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


async def _get(client: httpx.AsyncClient, url: str, **kw: Any) -> httpx.Response:
    """GET with a polite pause; on 429 back off (Retry-After if given) and retry."""
    for attempt in range(5):
        await asyncio.sleep(0.1)
        response = await client.get(url, **kw)
        if response.status_code != 429:
            return response
        retry_after = response.headers.get("Retry-After", "")
        await asyncio.sleep(int(retry_after) if retry_after.isdigit() else 5 * 2**attempt)
    return response  # ponytail: still 429 after ~2.5min -> caller raises/skips


def _parse_mcp_result(body: dict[str, Any]) -> dict[str, str]:
    """search_jobs JSON-RPC reply -> {offer_id: detail_path}. The tool returns
    title/company/salary but no description, so detail pages are still fetched."""
    jobs = json.loads(body["result"]["content"][0]["text"])["jobs"]
    paths: dict[str, str] = {}
    for job in jobs:
        path = urlsplit(job["url"]).path  # drops ?utm_source=mcp
        match = _OFFER_PATH_RE.match(path)
        if match:
            paths[match.group(1)] = path
    return paths


async def _search_mcp(client: httpx.AsyncClient, keywords: list[str]) -> dict[str, str]:
    """Discovery through the public MCP endpoint: one call per keyword, newest
    first. ponytail: capped at 50 hits/keyword, no pagination upstream."""
    headers = {"Accept": "application/json, text/event-stream"}

    async def rpc(method: str, params: dict | None = None, id: int | None = None) -> httpx.Response:
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if id is not None:
            msg["id"] = id
        return await client.post(MCP_URL, json=msg, headers=headers)

    init = await rpc(
        "initialize",
        {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "jobsearch", "version": "0"}},
        id=1,
    )
    init.raise_for_status()
    if sid := init.headers.get("Mcp-Session-Id"):
        headers["Mcp-Session-Id"] = sid
    await rpc("notifications/initialized")

    async def search(i: int, keyword: str) -> dict[str, str]:
        response = await rpc(
            "tools/call",
            {"name": "search_jobs", "arguments": {"phrase": keyword, "sortOrder": "newest"}},
            id=i,
        )
        response.raise_for_status()
        return _parse_mcp_result(response.json())

    paths: dict[str, str] = {}
    for found in await asyncio.gather(*(search(i, k) for i, k in enumerate(keywords, start=2))):
        paths.update(found)
    return paths


async def _search_html(client: httpx.AsyncClient, keywords: list[str], max_pages: int) -> dict[str, str]:
    async def search(keyword: str) -> dict[str, str]:
        found: dict[str, str] = {}
        for page in range(1, max_pages + 1):
            response = await _get(client, "/search", params={"q": keyword, "page": page})
            response.raise_for_status()
            page_paths = _parse_search_page(response.text)
            if not page_paths:
                break
            found.update(page_paths)
        return found

    paths: dict[str, str] = {}
    for found in await asyncio.gather(*(search(k) for k in keywords)):
        paths.update(found)
    return paths


async def ingest_eldorado(
    session: AsyncSession,
    keywords: list[str],
    max_pages: int = 2,
    on_progress: Callable[[int, int], None] | None = None,
) -> int:
    """Search each keyword, fetch detail pages for offers we haven't seen yet,
    upsert. Returns the number of new postings."""
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=HEADERS, timeout=30.0, follow_redirects=True
    ) as client:
        key = tuple(sorted(keywords))
        cached = _search_cache.get(key)
        if cached and time.monotonic() - cached[0] < SEARCH_TTL:
            paths = cached[1]
        else:
            try:
                paths = await _search_mcp(client, keywords)
            except (httpx.HTTPError, KeyError, ValueError, IndexError):  # experimental endpoint
                paths = await _search_html(client, keywords, max_pages)
            _search_cache[key] = (time.monotonic(), paths)

        known = set(
            await session.scalars(
                select(JobPosting.source_id).where(
                    JobPosting.source == SOURCE, JobPosting.source_id.in_(paths)
                )
            )
        )

        new_offer_ids = [o for o in paths if o not in known][:MAX_NEW_PER_RUN]
        rows = []
        done = 0
        gate = asyncio.Semaphore(CONCURRENCY)

        async def fetch(offer_id: str) -> None:
            nonlocal done
            async with gate:
                response = await _get(client, paths[offer_id])
            if response.status_code == 200:
                row = _parse_detail_page(response.text, offer_id)
                if row is not None:
                    rows.append(row)
            done += 1
            if on_progress:
                on_progress(done, len(new_offer_ids))

        await asyncio.gather(*(fetch(o) for o in new_offer_ids))

    return await upsert_job_postings(session, rows)
