"""Try a job board against the live site, then save it to boards.json.

    uv run python -m cli.add_board \
        --name justjoin \
        --search-url "https://justjoin.it/job-offers/all-locations/{keyword}?page={page}" \
        --link-selector "a[href*='/offers/']" \
        --keyword react

It fetches one search page, shows the offer links the selector found, fetches
the first one and prints the row it would store. Nothing is written until you
pass --save, so a wrong selector costs one HTTP request, not a polluted database.

The selector is the only thing you have to work out by hand: open the board's
search page, right-click an offer title, Inspect, and find something that matches
the offer links and nothing else. `a[href*='/offers/']` style link filters beat
class names, which are usually generated and change on every deploy.
"""

import argparse
import asyncio
import json
import sys

import httpx

from jobsearch.services.ingest_board import (
    _HEADERS,
    BOARDS_PATH,
    BoardConfig,
    parse_jsonld_posting,
    parse_links,
)


async def probe(config: BoardConfig, keyword: str) -> bool:
    url = config.search_url.format(keyword=keyword, page=1)
    print(f"GET {url}")
    async with httpx.AsyncClient(headers=_HEADERS, timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url)
        print(f"  -> {response.status_code}, {len(response.text)} bytes")
        if response.status_code != 200:
            print("  the board refused the request — it may need a browser, or block scrapers")
            return False

        offers = parse_links(response.text, url, config)
        if not offers:
            print(f"  no links matched {config.link_selector!r}.")
            print("  Either the selector is wrong, or results are rendered by JS — view-source")
            print("  the page and search for an offer title. Not there = JS, and this driver")
            print("  cannot read it; that board needs a Playwright module instead.")
            return False

        print(f"  {len(offers)} offers found. First three ids -> urls:")
        for source_id in list(offers)[:3]:
            print(f"    {source_id}  {offers[source_id]}")

        source_id, offer_url = next(iter(offers.items()))
        print(f"\nGET {offer_url}")
        detail = await client.get(offer_url)
        row = parse_jsonld_posting(detail.text, config.name, source_id, offer_url)

    if row is None:
        print("  no schema.org JobPosting on the detail page — this board needs its own parser.")
        return False

    print("  row it would store:")
    for key, value in row.items():
        text = str(value)
        print(f"    {key:16} {text[:100]}{'…' if len(text) > 100 else ''}")
    if len(row["description_text"]) < 200:
        print("\n  ⚠ description is very short — scoring quality depends on it. Check the page")
        print("    keeps its description outside <main>, or the JSON-LD is a stub.")
    return True


def save(config: BoardConfig) -> None:
    boards = json.loads(BOARDS_PATH.read_text()) if BOARDS_PATH.exists() else []
    boards = [board for board in boards if board.get("name") != config.name]  # re-adding replaces
    boards.append(config.model_dump())
    BOARDS_PATH.write_text(json.dumps(boards, indent=2) + "\n")
    print(f"\nsaved to {BOARDS_PATH}. The next pipeline run includes it.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="source key, e.g. justjoin")
    parser.add_argument("--search-url", required=True, help="template with {keyword} and optional {page}")
    parser.add_argument("--link-selector", required=True, help="CSS selector matching offer links")
    parser.add_argument("--id-pattern", help="regex over the offer path; group 1 = id. Default: the path")
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--keyword", default="react", help="keyword to probe with")
    parser.add_argument("--save", action="store_true", help="write to boards.json if the probe works")
    args = parser.parse_args()

    if "{keyword}" not in args.search_url:
        sys.exit("--search-url must contain {keyword}")

    config = BoardConfig(
        name=args.name,
        search_url=args.search_url,
        link_selector=args.link_selector,
        id_pattern=args.id_pattern,
        max_pages=args.max_pages,
    )
    if not asyncio.run(probe(config, args.keyword)):
        sys.exit("\nnot saved.")
    if args.save:
        save(config)
    else:
        print("\nlooks good — rerun with --save to keep it.")
