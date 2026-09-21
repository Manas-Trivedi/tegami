#!/usr/bin/env python3

import argparse
import csv
import email
import imaplib
import os
import re
import time
from datetime import datetime, timezone
from email.header import decode_header
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
HARD_BOUNCES = ROOT / "state" / "hard_bounces.csv"

# Confirmed permanent mailbox failures.
HARD_BOUNCE_CODES = {
    "5.1.1",
    "5.1.2",
    "5.1.10",
}

# Typical bounce senders.
BOUNCE_SENDERS = {
    "mailer-daemon",
    "postmaster",
}

EMAIL_RE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)


def decode_header_value(value):
    if not value:
        return ""

    parts = decode_header(value)
    result = []

    for part, encoding in parts:
        if isinstance(part, bytes):
            result.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            result.append(part)

    return "".join(result)


def extract_emails(text):
    return {
        match.lower()
        for match in EMAIL_RE.findall(text or "")
    }


def is_bounce_message(msg):
    sender = (msg.get("From") or "").lower()
    subject = decode_header_value(msg.get("Subject") or "").lower()

    sender_matches = any(
        sender.startswith(name) or f"<{name}@" in sender
        for name in BOUNCE_SENDERS
    )

    subject_matches = any(
        phrase in subject
        for phrase in (
            "delivery status notification",
            "delivery failure",
            "delivery failed",
            "mail delivery failed",
            "undeliverable",
            "returned mail",
            "failure notice",
        )
    )

    return sender_matches or subject_matches


def get_message_text(msg):
    chunks = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()

            if content_type not in ("text/plain", "message/delivery-status"):
                continue

            payload = part.get_payload(decode=True)

            if payload:
                charset = part.get_content_charset() or "utf-8"
                chunks.append(
                    payload.decode(charset, errors="replace")
                )
    else:
        payload = msg.get_payload(decode=True)

        if payload:
            charset = msg.get_content_charset() or "utf-8"
            chunks.append(
                payload.decode(charset, errors="replace")
            )

    return "\n".join(chunks)


def extract_recipient(text):
    patterns = [
        # RFC-style delivery report.
        r"Final-Recipient:\s*rfc822;\s*([^\s;<>]+@[^\s;<>]+)",

        # Common Gmail/Outlook wording.
        r"(?:recipient|recipient address|original recipient)"
        r"[:\s]+(?:rfc822;)?\s*<?([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})>?",

        # "Your message to foo@example.com..."
        r"(?:message|email)\s+to\s+([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",

        # "The email account ... foo@example.com ..."
        r"(?:account|address).*?"
        r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)

        if match:
            return match.group(1).lower().strip(".,<>")

    return None


def extract_status(text):
    match = re.search(
        r"\bstatus\s*:\s*(\d\.\d\.\d)\b",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1)

    # Also catch errors like:
    # 550 5.1.1
    match = re.search(
        r"\b(?:error|smtp|response|status code)?"
        r".{0,30}\b([245]\.\d\.\d)\b",
        text,
        re.IGNORECASE,
    )

    return match.group(1) if match else None


def load_existing_bounces():
    existing = set()

    if not HARD_BOUNCES.exists():
        return existing

    with HARD_BOUNCES.open(
        encoding="utf-8",
        newline="",
    ) as fh:
        reader = csv.DictReader(fh)

        for row in reader:
            email_addr = (row.get("email") or "").strip().lower()

            if email_addr:
                existing.add(email_addr)

    return existing


def save_bounces(bounces):
    if not bounces:
        return

    HARD_BOUNCES.parent.mkdir(parents=True, exist_ok=True)

    file_exists = HARD_BOUNCES.exists()

    with HARD_BOUNCES.open(
        "a",
        encoding="utf-8",
        newline="",
    ) as fh:
        writer = csv.writer(fh)

        if not file_exists:
            writer.writerow([
                "email",
                "reason",
                "detected_at",
            ])

        for bounce in bounces:
            writer.writerow([
                bounce["email"],
                bounce["reason"],
                bounce["detected_at"],
            ])


def process_message(msg, existing):
    if not is_bounce_message(msg):
        return None

    text = get_message_text(msg)

    recipient = extract_recipient(text)

    if not recipient:
        # Last-resort extraction, but only from a message
        # already classified as a bounce.
        candidates = extract_emails(text)

        if len(candidates) == 1:
            recipient = next(iter(candidates))

    if not recipient:
        return None

    status = extract_status(text)

    if status not in HARD_BOUNCE_CODES:
        return None

    if recipient in existing:
        return None

    return {
        "email": recipient,
        "reason": status,
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Watch Gmail for confirmed hard-bounce notifications."
    )

    parser.add_argument(
        "--minutes",
        type=float,
        default=1,
        help="How long to watch (default: 1 minute)",
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=5,
        help="Seconds between mailbox checks (default: 5)",
    )

    args = parser.parse_args()

    load_dotenv(ROOT / "mailer" / ".env")

    username = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")

    if not username or not password:
        raise SystemExit(
            "SMTP_USER and SMTP_PASS must be set in mailer/.env"
        )

    existing = load_existing_bounces()

    print(f"Watching Gmail for {args.minutes:g} minutes...")
    print(f"Existing hard bounces: {len(existing)}")

    start = time.time()
    seen_message_ids = set()
    new_bounces = []

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(username, password)

        while time.time() - start < args.minutes * 60:
            mail.select("INBOX")

            # Search only messages that arrived recently.
            status, data = mail.search(None, "UNSEEN")

            if status == "OK":
                message_ids = data[0].split()

                for message_id in message_ids:
                    if message_id in seen_message_ids:
                        continue

                    seen_message_ids.add(message_id)

                    status, message_data = mail.fetch(
                        message_id,
                        "(RFC822)",
                    )

                    if status != "OK":
                        continue

                    for response in message_data:
                        if not isinstance(response, tuple):
                            continue

                        msg = email.message_from_bytes(response[1])

                        bounce = process_message(
                            msg,
                            existing,
                        )

                        if bounce:
                            new_bounces.append(bounce)
                            existing.add(bounce["email"])

                            print(
                                f"HARD BOUNCE: "
                                f"{bounce['email']} "
                                f"({bounce['reason']})"
                            )

            remaining = max(
                0,
                int(args.minutes * 60 - (time.time() - start)),
            )

            if remaining:
                time.sleep(min(args.interval, remaining))

    finally:
        try:
            mail.logout()
        except Exception:
            pass

    save_bounces(new_bounces)

    print()
    print(f"New hard bounces: {len(new_bounces)}")

    if new_bounces:
        print(f"Saved to: {HARD_BOUNCES}")
    else:
        print("No new confirmed hard bounces found.")


if __name__ == "__main__":
    main()