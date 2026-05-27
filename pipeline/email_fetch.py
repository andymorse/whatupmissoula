"""Read-only IMAP fetch of weekly-ad emails + extraction of the flyer link.

Flyer emails don't attach the ad — they link to a web-hosted weekly ad (usually a
tracking redirect that lands on a Flipp/store SPA). So this module:

  1. finds flyer emails — from a known store sender (config stores[].senders) AND
     a flyer-ish subject (config email.subject_hints), which keeps welcome /
     receipt / account emails out;
  2. pulls the best "view the weekly ad" link out of the HTML body.

The renderer (web_flyer) then screenshots that URL. Strictly READ-ONLY: the
mailbox is opened readonly and nothing is ever deleted or flagged.
"""
from __future__ import annotations

import email
import imaplib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.header import decode_header
from email.message import Message

from settings import env


@dataclass
class FlyerEmail:
    store: str
    sender: str
    subject: str
    date: str
    flyer_url: str | None


def fetch_flyer_emails(cfg: dict) -> list[FlyerEmail]:
    host = env("IMAP_HOST", "imap.gmail.com")
    user, pw = env("IMAP_USER"), env("IMAP_APP_PASSWORD")
    if not (user and pw):
        raise RuntimeError("IMAP_USER / IMAP_APP_PASSWORD not set in .env")

    ecfg = cfg.get("email", {})
    mapping = _store_senders(cfg)
    hints = [h.lower() for h in ecfg.get("subject_hints", [])]
    since = (datetime.now() - timedelta(days=ecfg.get("lookback_days", 8))).strftime("%d-%b-%Y")

    found: list[FlyerEmail] = []
    # Dedup key includes the To: address because some senders (Yoke's via
    # Mailchimp) use the same sender+subject for every location and encode the
    # store choice in per-recipient redirects. Two signups (one alias per
    # location) → two distinct emails to different To: addresses → must keep
    # both. Same campaign delivered twice to the same To still gets deduped.
    seen: set[tuple[str, str, str]] = set()
    M = imaplib.IMAP4_SSL(host, int(env("IMAP_PORT", "993")))
    try:
        M.login(user, pw)
        M.select("INBOX", readonly=True)          # read-only — cannot modify mail
        typ, data = M.search(None, f"(SINCE {since})")
        for num in data[0].split():
            typ, md = M.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(md[0][1])
            sender = email.utils.parseaddr(msg.get("From", ""))[1]
            store = _store_for(sender, mapping)
            if not store:
                continue
            subject = _decode(msg.get("Subject", ""))
            if hints and not any(h in subject.lower() for h in hints):
                continue                          # known sender, but not a flyer (e.g. welcome)
            to_addr = email.utils.parseaddr(msg.get("To", ""))[1].lower()
            key = (sender.lower(), subject.strip().lower(), to_addr)
            if key in seen:
                continue                          # same campaign delivered twice to same recipient
            seen.add(key)
            html = _html_body(msg)
            url = extract_flyer_link(html, ecfg) if html else None
            found.append(FlyerEmail(store, sender, subject, msg.get("Date", ""), url))
    finally:
        try:
            M.logout()
        except Exception:
            pass
    return found


def extract_flyer_link(html: str, ecfg: dict) -> str | None:
    """Score anchors by text/alt/url against link_keywords; skip link_exclude."""
    kws = [k.lower() for k in ecfg.get("link_keywords", [])]
    excl = [e.lower() for e in ecfg.get("link_exclude", [])]
    best, best_score = None, 0
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.I | re.S):
        url, inner = m.group(1), m.group(2)
        u = url.lower()
        if u.startswith(("mailto:", "tel:", "#")):
            continue
        text = re.sub(r"<[^>]+>", " ", inner)
        text += " " + " ".join(re.findall(r'alt="([^"]*)"', inner, re.I))
        text = re.sub(r"\s+", " ", text).strip().lower()
        if any(e in u or e in text for e in excl):
            continue
        score = sum(2 for k in kws if k in text) + sum(1 for k in kws if k in u)
        if score > best_score:
            best, best_score = url, score
    return best


# --- helpers ---------------------------------------------------------------

def _store_senders(cfg: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for s in cfg.get("stores", []):
        for pat in (s.get("senders") or []):
            out.append((s["name"], pat.lower()))
    return out


def _store_for(sender: str, mapping: list[tuple[str, str]]) -> str | None:
    sender = sender.lower()
    for store, pat in mapping:
        if (pat.startswith("*.") and sender.endswith(pat[1:])) or sender == pat:
            return store
    return None


def _decode(raw: str) -> str:
    parts = []
    for txt, enc in decode_header(raw):
        if isinstance(txt, bytes):
            parts.append(txt.decode(enc or "utf-8", "ignore"))
        else:
            parts.append(txt)
    return "".join(parts)


def _html_body(msg: Message) -> str | None:
    html = ""
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True)
            if payload:
                html += payload.decode(part.get_content_charset() or "utf-8", "ignore")
    return html or None
