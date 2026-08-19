"""The generic board driver. A wrong link parse either stores nothing or stores
the board's nav menu as jobs, and both are quiet failures."""

import json

from jobsearch.services.ingest_board import BoardConfig, load_boards, parse_jsonld_posting, parse_links

SEARCH_HTML = """
<html><body>
  <nav><a href="/about">About us</a></nav>
  <ul>
    <li class="card"><a href="/offers/1234-react-dev?utm_source=x">React Dev</a></li>
    <li class="card"><a href="/offers/5678-vue-dev">Vue Dev</a></li>
  </ul>
</body></html>
"""

DETAIL_HTML = """
<html><head><script type="application/ld+json">
{"@type": "JobPosting", "title": "React Developer",
 "hiringOrganization": {"name": "Acme"},
 "jobLocation": [{"address": {"addressLocality": "Warsaw"}}],
 "datePosted": "2026-08-01", "url": "https://board.test/offers/1234"}
</script></head><body><main>We use React and TypeScript.</main></body></html>
"""


def _config(**overrides) -> BoardConfig:
    return BoardConfig(
        **{
            "name": "testboard",
            "search_url": "https://board.test/search?q={keyword}&page={page}",
            "link_selector": "li.card",
            **overrides,
        }
    )


def test_selector_picks_offer_links_and_ignores_the_nav():
    offers = parse_links(SEARCH_HTML, "https://board.test/search", _config())
    assert len(offers) == 2
    assert "/about" not in offers


def test_tracking_params_are_stripped_from_the_id():
    # ?utm_source changes per visit; keeping it makes every rerun look like a new offer
    offers = parse_links(SEARCH_HTML, "https://board.test/search", _config())
    assert "/offers/1234-react-dev" in offers


def test_relative_hrefs_become_absolute_urls():
    offers = parse_links(SEARCH_HTML, "https://board.test/search", _config())
    assert offers["/offers/1234-react-dev"].startswith("https://board.test/offers/1234")


def test_id_pattern_extracts_a_stable_numeric_id():
    offers = parse_links(SEARCH_HTML, "https://board.test/s", _config(id_pattern=r"/offers/(\d+)-"))
    assert set(offers) == {"1234", "5678"}


def test_json_ld_maps_onto_a_posting_row():
    row = parse_jsonld_posting(DETAIL_HTML, "testboard", "1234", "https://board.test/offers/1234")
    assert row["title"] == "React Developer"
    assert row["company"] == "Acme"
    assert row["location"] == "Warsaw"
    # body text, not the JSON-LD description — that's where the stack is listed
    assert "TypeScript" in row["description_text"]
    assert row["remote"] is False  # a jobLocation and no TELECOMMUTE means on-site


def test_json_ld_inside_a_list_is_still_found():
    html = DETAIL_HTML.replace('{"@type": "JobPosting"', '[{"@type": "WebSite"}, {"@type": "JobPosting"').replace(
        "</script>", "]</script>"
    )
    assert parse_jsonld_posting(html, "b", "1", "u")["title"] == "React Developer"


def test_unparseable_date_does_not_lose_the_posting():
    html = DETAIL_HTML.replace('"2026-08-01"', '"last Tuesday"')
    row = parse_jsonld_posting(html, "b", "1", "u")
    assert row is not None and row["posted_at"] is None


def test_page_without_json_ld_is_skipped():
    assert parse_jsonld_posting("<main>plain page</main>", "b", "1", "u") is None


def test_boards_file_is_optional_and_disabled_boards_are_skipped(tmp_path):
    assert load_boards(tmp_path / "nope.json") == []
    path = tmp_path / "boards.json"
    path.write_text(json.dumps([
        {"name": "on", "search_url": "https://a.test/{keyword}", "link_selector": "a"},
        {"name": "off", "search_url": "https://b.test/{keyword}", "link_selector": "a", "enabled": False},
    ]))
    assert [board.name for board in load_boards(path)] == ["on"]
