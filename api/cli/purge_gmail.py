"""Trash job-alert mail older than N days from the configured senders.

`ingest_gmail` only ever touches UNSEEN mail in INBOX, so already-read and
archived alerts pile up forever. This sweeps them.

Run: uv run python -m cli.purge_gmail            # dry run, prints counts
     uv run python -m cli.purge_gmail --yes      # actually trash
     uv run python -m cli.purge_gmail --days 30 --mailbox INBOX --yes
     uv run python -m cli.purge_gmail --from a@x.com,b@y.com --yes
"""

import argparse
from datetime import UTC, datetime, timedelta

from jobsearch.config import get_settings
from jobsearch.services.ingest_gmail import _connect, special_folder

CHUNK = 500  # messages per COPY/STORE command


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--mailbox", help="default: the account's All Mail folder")
    # GMAIL_SENDERS also decides what ingest feeds the LLM, so senders worth deleting
    # but not worth reading (marketing, dead alert addresses) belong here instead
    parser.add_argument("--from", dest="senders", help="comma-separated, overrides GMAIL_SENDERS")
    parser.add_argument("--yes", action="store_true", help="without this it only reports")
    args = parser.parse_args()

    senders = [s.strip() for s in (args.senders or "").split(",") if s.strip()] or get_settings().gmail_senders
    if not senders:
        raise SystemExit("no senders — set GMAIL_SENDERS or pass --from")

    before = (datetime.now(UTC) - timedelta(days=args.days)).strftime("%d-%b-%Y")
    client = _connect()
    try:
        # read alerts get archived out of INBOX, so sweep All Mail by default
        mailbox = f'"{args.mailbox}"' if args.mailbox else special_folder(client, "\\All")
        trash = special_folder(client, "\\Trash")
        client.select(mailbox)  # _connect selected settings.gmail_mailbox
        total = 0
        for sender in senders:
            # UID, not sequence numbers: Gmail has auto-expunge on, so the first
            # \\Deleted renumbers everything after it and later chunks would hit
            # the wrong messages. UIDs never shift.
            _, data = client.uid("SEARCH", None, "FROM", f'"{sender}"', "BEFORE", before)
            uids = data[0].split()
            print(f"{len(uids):5d}  {sender}")
            total += len(uids)
            if not uids or not args.yes:
                continue
            # in Gmail only a copy to Trash really deletes, and it stays
            # recoverable for 30 days. Chunked — a comma list of thousands of
            # ids overruns the IMAP command line.
            for start in range(0, len(uids), CHUNK):
                uid_set = b",".join(uids[start : start + CHUNK]).decode()
                client.uid("COPY", uid_set, trash)
                client.uid("STORE", uid_set, "+FLAGS", "\\Deleted")
        print(f"\n{total} mails before {before} in {mailbox}"
              f"{' — moved to Trash' if args.yes else ' — dry run, pass --yes to trash'}")
    finally:
        client.logout()


if __name__ == "__main__":
    main()
