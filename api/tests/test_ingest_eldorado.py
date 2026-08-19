from jobsearch.services.ingest_eldorado import _parse_detail_page, _parse_search_page

SEARCH_HTML = """
<div data-offer-id="261752">
  <a href="/praca/261752-senior-react-native-developer-power-media?ctx=abc123">card</a>
</div>
<div data-offer-id="999">
  <a href="/praca/firma/allegro">not an offer link</a>
</div>
"""

DETAIL_HTML = """
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "JobPosting",
 "title": "Senior React Native Developer",
 "datePosted": "2026-01-12",
 "hiringOrganization": {"@type": "Organization", "name": "Power Media"},
 "url": "https://czyjesteldorado.pl/praca/261752-senior-react-native-developer-power-media",
 "jobLocation": [{"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "Gdansk"}}],
 "description": "short"}
</script>
<main>Senior React Native Developer 19k - 26k PLN React Native PostgreSQL AWS</main>
"""


def test_parse_search_page_extracts_offer_paths_and_strips_tracking():
    paths = _parse_search_page(SEARCH_HTML)
    assert paths == {"261752": "/praca/261752-senior-react-native-developer-power-media"}


def test_parse_detail_page_maps_json_ld_and_body_text():
    row = _parse_detail_page(DETAIL_HTML, "261752")
    assert row["source"] == "eldorado"
    assert row["source_id"] == "261752"
    assert row["title"] == "Senior React Native Developer"
    assert row["company"] == "Power Media"
    assert row["location"] == "Gdansk"
    assert row["url"] == "https://czyjesteldorado.pl/praca/261752-senior-react-native-developer-power-media"
    assert "PostgreSQL" in row["description_text"]
    assert row["posted_at"].isoformat() == "2026-01-12T00:00:00+00:00"


def test_parse_detail_page_without_json_ld_returns_none():
    assert _parse_detail_page("<main>no structured data</main>", "1") is None


def _detail_html(*, extra: str) -> str:
    return (
        '<script type="application/ld+json">'
        '{"@context": "https://schema.org", "@type": "JobPosting", "title": "Dev", '
        '"url": "https://czyjesteldorado.pl/praca/1-dev", "description": "d"' + extra + "}"
        "</script><main>body</main>"
    )


def test_remote_is_true_only_when_the_page_says_telecommute():
    # the three states must stay distinct: a wrong False would hide a remote job
    # from the "Remote" filter, and a wrong True would surface an office-only one
    assert _parse_detail_page(_detail_html(extra=', "jobLocationType": "TELECOMMUTE"'), "1")["remote"] is True
    assert (
        _parse_detail_page(
            _detail_html(extra=', "jobLocation": [{"address": {"addressLocality": "Gdansk"}}]'), "1"
        )["remote"]
        is False
    )
    # said nothing at all -> unknown, which the filter excludes from both sides
    assert _parse_detail_page(_detail_html(extra=""), "1")["remote"] is None
