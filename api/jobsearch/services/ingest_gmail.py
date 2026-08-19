"""Reads job-alert mail over IMAP and turns each alert into posting rows.

IMAP with an app password rather than the Gmail API: no OAuth flow to run on a
headless box, no google client libraries, and `imaplib` is stdlib. The account
needs 2FA enabled and an app password generated for it.

Alert mails are lists of jobs in HTML, with layouts that change whenever the
sender feels like it, so extraction is one structured LLM call per mail instead of
per-sender parsers.
"""

import email
import email.utils
import imaplib
from datetime import datetime
from email.message import Message
from typing import Any, Callable

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from jobsearch.config import get_settings
from jobsearch.database.operations.job_posting import upsert_job_postings
from jobsearch.services.ingest_remoteok import _strip_html  # same job: HTML -> plain text
from jobsearch.services.llm import get_openai_client

SOURCE = "gmail"
MAX_BODY_CHARS = 20000  # alert mails are mostly markup; the job list is near the top

_SYSTEM_PROMPT = (
    "You extract job postings from a job-alert email. Return one entry per distinct "
    "job advertised. `url` must be the link that opens that job (a tracking redirect "
    "is fine). `description` is whatever the mail says about the role — do not invent "
    "requirements. If the mail advertises no jobs, return an empty list."
)


class ExtractedPosting(BaseModel):
    title: str
    company: str | None = None
    location: str | None = None
    url: str
    description: str = ""


class ExtractedPostings(BaseModel):
    postings: list[ExtractedPosting]


def message_text(message: Message) -> str:
    """Plain text of a mail, preferring a text/plain part and falling back to
    stripped HTML."""
    plain: list[str] = []
    html: list[str] = []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        (plain if part.get_content_type() == "text/plain" else html).append(text)

    if plain:
        return "\n".join(plain).strip()
    return _strip_html("\n".join(html))


async def _extract_postings(body: str) -> list[ExtractedPosting]:
    response = await get_openai_client().chat.completions.parse(
        model=get_settings().openai_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": body[:MAX_BODY_CHARS]},
        ],
        response_format=ExtractedPostings,
    )
    return response.choices[0].message.parsed.postings


def sent_at(message: Message) -> datetime | None:
    raw = message.get("Date")
    if not raw:
        return None
    try:
        return email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):  # malformed Date header must not lose the mail
        return None


def _to_rows(message_id: str, sent_at: datetime | None, postings: list[ExtractedPosting]) -> list[dict[str, Any]]:
    return [
        {
            "source": SOURCE,
            # Message-ID is stable, so re-reading a mail upserts instead of duplicating —
            # which matters when the run stores postings but then fails to trash the mail
            "source_id": f"{message_id}:{index}",
            "title": posting.title,
            "company": posting.company,
            "location": posting.location,
            "url": posting.url,
            "description_text": posting.description,
            "posted_at": sent_at,
        }
        for index, posting in enumerate(postings)
    ]


def special_folder(client: imaplib.IMAP4_SSL, attribute: str) -> str:
    r"""Name of the folder LIST flags with `attribute` (e.g. "\\Trash", "\\All").

    Hardcoding "[Gmail]/Trash" only works on English accounts — a Polish one calls
    it "[Gmail]/Kosz". The special-use flag is the same in every language.
    Quoted because the real names contain spaces and imaplib does not quote."""
    _, folders = client.list()
    for line in folders:
        text = line.decode()
        if attribute in text.split(")")[0]:
            return '"' + text.rsplit(' "', 1)[-1].strip('"') + '"'
    raise RuntimeError(f"no IMAP folder flagged {attribute} on this account")


def _connect() -> imaplib.IMAP4_SSL:
    settings = get_settings()
    if not settings.gmail_user or not settings.gmail_app_password:
        raise RuntimeError("GMAIL_USER and GMAIL_APP_PASSWORD must be set to ingest mail")
    client = imaplib.IMAP4_SSL("imap.gmail.com")
    client.login(settings.gmail_user, settings.gmail_app_password)
    client.select(settings.gmail_mailbox)
    return client


def _search_senders(client: imaplib.IMAP4_SSL, senders: list[str]) -> list[bytes]:
    """UIDs of unseen mail from these senders — one SEARCH each, IMAP's nested OR
    syntax buys nothing here.

    UIDs rather than sequence numbers: Gmail has auto-expunge on, so the first
    mail we trash renumbers every mail after it and the rest of the loop would
    fetch and delete the wrong ones."""
    found: list[bytes] = []
    for sender in senders:
        _, data = client.uid("SEARCH", None, "UNSEEN", "FROM", f'"{sender}"')
        found.extend(data[0].split())
    return sorted(set(found), key=int)


def _finish_message(client: imaplib.IMAP4_SSL, uid: bytes) -> None:
    """Mail leaves the inbox only after its postings are committed.

    In Gmail, flagging \\Deleted and expunging merely removes the label; copying to
    the Trash folder is what actually deletes, and keeps 30 days of recovery."""
    if get_settings().gmail_after_ingest == "keep":
        client.uid("STORE", uid, "+FLAGS", "\\Seen")
        return
    client.uid("COPY", uid, special_folder(client, "\\Trash"))
    client.uid("STORE", uid, "+FLAGS", "\\Deleted")


async def ingest_gmail(session: AsyncSession, on_progress: Callable[[int, int], None] | None = None) -> int:
    """Read unseen alert mail from the configured senders, store the postings, then
    trash each mail. Returns the number of postings stored."""
    settings = get_settings()
    if not settings.gmail_senders:
        return 0

    client = _connect()
    stored = 0
    try:
        uids = _search_senders(client, settings.gmail_senders)
        for i, uid in enumerate(uids):
            _, data = client.uid("FETCH", uid, "(RFC822)")
            message = email.message_from_bytes(data[0][1])
            message_id = message.get("Message-ID") or f"unknown:{uid.decode()}"

            postings = await _extract_postings(message_text(message))
            rows = _to_rows(message_id, sent_at(message), postings)
            if rows:
                stored += await upsert_job_postings(session, rows)
            _finish_message(client, uid)
            if on_progress:
                on_progress(i + 1, len(uids))
        client.expunge()
    finally:
        client.logout()
    return stored
