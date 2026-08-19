"""Mail parsing, no IMAP and no LLM. The risky parts here are silent: a mail whose
text we fail to extract yields zero postings and still gets trashed."""

from email.message import EmailMessage

import pytest

from jobsearch.services.ingest_gmail import (
    ExtractedPosting,
    _to_rows,
    message_text,
    sent_at,
    special_folder,
)


def _mail(*, plain: str | None = None, html: str | None = None, date: str | None = None) -> EmailMessage:
    message = EmailMessage()
    message["From"] = "jobs-noreply@linkedin.com"
    if date:
        message["Date"] = date
    if plain and html:
        message.set_content(plain)
        message.add_alternative(html, subtype="html")
    elif html:
        message.set_content(html, subtype="html")
    else:
        message.set_content(plain or "")
    return message


def test_prefers_the_plain_text_part():
    text = message_text(_mail(plain="Senior Python Developer at Acme", html="<p>markup version</p>"))

    assert text == "Senior Python Developer at Acme"


def test_falls_back_to_stripped_html_when_there_is_no_plain_part():
    text = message_text(_mail(html="<div><h1>React Developer</h1><p>Warsaw &amp; remote</p></div>"))

    assert "React Developer" in text
    assert "Warsaw & remote" in text
    assert "<" not in text


def test_missing_and_malformed_date_headers_do_not_raise():
    assert sent_at(_mail(plain="x")) is None
    assert sent_at(_mail(plain="x", date="not a date")) is None
    assert sent_at(_mail(plain="x", date="Tue, 11 Aug 2026 09:30:00 +0200")) is not None


def test_source_id_is_stable_per_message_and_position():
    postings = [
        ExtractedPosting(title="A", url="https://a.example"),
        ExtractedPosting(title="B", url="https://b.example"),
    ]

    rows = _to_rows("<abc@mail.gmail.com>", None, postings)

    assert [row["source_id"] for row in rows] == ["<abc@mail.gmail.com>:0", "<abc@mail.gmail.com>:1"]
    assert {row["source"] for row in rows} == {"gmail"}
    # re-reading the same mail must produce the same keys, so upsert dedupes it
    assert [row["source_id"] for row in _to_rows("<abc@mail.gmail.com>", None, postings)] == [
        row["source_id"] for row in rows
    ]


class _FakeClient:
    """Just enough IMAP to answer LIST."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode() for line in lines]

    def list(self) -> tuple[str, list[bytes]]:
        return "OK", self._lines


_POLISH = [
    '(\\HasNoChildren) "/" "INBOX"',
    '(\\HasChildren \\Noselect) "/" "[Gmail]"',
    '(\\HasNoChildren \\Trash) "/" "[Gmail]/Kosz"',
    '(\\All \\HasNoChildren) "/" "[Gmail]/Wszystkie"',
]
_ENGLISH = [
    '(\\HasNoChildren) "/" "INBOX"',
    '(\\HasNoChildren \\Trash) "/" "[Gmail]/Trash"',
    '(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"',
]


def test_special_folder_reads_the_flag_not_the_name():
    # the whole point: a Polish account calls Trash "Kosz"
    assert special_folder(_FakeClient(_POLISH), "\\Trash") == '"[Gmail]/Kosz"'
    assert special_folder(_FakeClient(_POLISH), "\\All") == '"[Gmail]/Wszystkie"'
    assert special_folder(_FakeClient(_ENGLISH), "\\Trash") == '"[Gmail]/Trash"'
    # quoted, because "All Mail" has a space and imaplib does not quote
    assert special_folder(_FakeClient(_ENGLISH), "\\All") == '"[Gmail]/All Mail"'


def test_special_folder_ignores_a_flag_that_only_appears_in_a_folder_name():
    lines = ['(\\HasNoChildren) "/" "My \\Trash notes"', '(\\HasNoChildren \\Trash) "/" "[Gmail]/Kosz"']

    assert special_folder(_FakeClient(lines), "\\Trash") == '"[Gmail]/Kosz"'


def test_special_folder_raises_when_the_account_has_no_such_folder():
    with pytest.raises(RuntimeError):
        special_folder(_FakeClient(['(\\HasNoChildren) "/" "INBOX"']), "\\All")
