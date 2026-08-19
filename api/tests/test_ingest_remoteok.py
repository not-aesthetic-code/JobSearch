from jobsearch.services.ingest_remoteok import _strip_html, _to_job_posting_row


def test_strip_html_removes_tags_and_unescapes_entities():
    assert _strip_html("<p>Hi &amp; welcome</p>") == "Hi & welcome"


def test_to_job_posting_row_skips_legal_notice_entry():
    assert _to_job_posting_row({"legal": "..."}) is None


def test_to_job_posting_row_maps_fields():
    item = {
        "id": "42",
        "position": "Backend Engineer",
        "company": "Acme",
        "location": "Remote",
        "url": "https://remoteok.com/remote-jobs/42",
        "description": "<p>Build things</p>",
        "date": "2026-07-04T16:00:08+00:00",
    }
    row = _to_job_posting_row(item)
    assert row == {
        "source": "remoteok",
        "source_id": "42",
        "title": "Backend Engineer",
        "company": "Acme",
        "location": "Remote",
        "url": "https://remoteok.com/remote-jobs/42",
        "description_text": "Build things",
        "remote": True,  # every RemoteOK posting is remote by definition
        "posted_at": row["posted_at"],  # datetime equality checked separately below
    }
    assert row["posted_at"].isoformat() == "2026-07-04T16:00:08+00:00"
