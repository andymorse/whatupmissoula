"""Read-only IMAP fetch of this week's flyer emails.

Connects to the mailbox, finds recent messages that look like store flyers, and
saves their attachments (PDF/image) to a working dir. NEVER deletes or marks
mail — strictly read-only.

Starting implementation: validate against the real mailbox once it's subscribed
to store flyer lists (sender list in config.yaml is the main thing to tune).
"""
from __future__ import annotations

import email
import imaplib
from datetime import datetime, timedelta
from email.message import Message
from pathlib import Path

from settings import env


def fetch_flyer_attachments(cfg: dict, work_dir: str | Path) -> list[Path]:
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    host = env("IMAP_HOST", cfg.get("email", {}).get("host", "imap.gmail.com"))
    user = env("IMAP_USER")
    pw = env("IMAP_APP_PASSWORD")
    if not (user and pw):
        raise RuntimeError("IMAP_USER / IMAP_APP_PASSWORD not set in .env")

    lookback = cfg["email"].get("lookback_days", 8)
    since = (datetime.now() - timedelta(days=lookback)).strftime("%d-%b-%Y")

    saved: list[Path] = []
    M = imaplib.IMAP4_SSL(host, int(env("IMAP_PORT", "993")))
    try:
        M.login(user, pw)
        M.select("INBOX", readonly=True)            # readonly — cannot modify mail
        typ, data = M.search(None, f'(SINCE {since})')
        for num in data[0].split():
            typ, msg_data = M.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            if not _looks_like_flyer(msg, cfg):
                continue
            sender = email.utils.parseaddr(msg.get("From", ""))[1]
            saved += _save_attachments(msg, work, sender)
    finally:
        try:
            M.logout()
        except Exception:
            pass
    return saved


def _looks_like_flyer(msg: Message, cfg: dict) -> bool:
    ecfg = cfg.get("email", {})
    sender = email.utils.parseaddr(msg.get("From", ""))[1].lower()
    allowed = [s.lower() for s in ecfg.get("allowed_senders", [])]
    if allowed:
        return any(_match(sender, a) for a in allowed)
    # No allow-list yet: fall back to subject hints so we don't grab everything.
    subj = (msg.get("Subject") or "").lower()
    return any(h in subj for h in ecfg.get("subject_hints", []))


def _match(sender: str, pattern: str) -> bool:
    if pattern.startswith("*."):
        return sender.endswith(pattern[1:])
    return sender == pattern


def _save_attachments(msg: Message, work: Path, sender: str) -> list[Path]:
    out: list[Path] = []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype in ("application/pdf",) or ctype.startswith("image/"):
            fn = part.get_filename() or f"{sender}-{len(out)}"
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            dest = work / f"{sender}__{fn}"
            dest.write_bytes(payload)
            out.append(dest)
    return out
