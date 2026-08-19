"""Email the owner that a draft is ready to review.

The weekly run is scheduled (see docs/deploy.md §8), but it deliberately stops
at a DRAFT — nothing reaches the live site without a human looking first. A
scheduled run that renders in silence is a run you forget to publish, so this
sends one plain-text summary the moment the draft exists: what landed, what
looks thin, and the exact command to publish it.

Sending is `smtplib` over the same Gmail account `email_fetch.py` already reads
with IMAP, so there's no new service, no new secret, and no new dependency —
the app password works for both. `REVIEW_NOTIFY_EMAIL` is the recipient (it has
been sitting unused in .env waiting for this); it falls back to IMAP_USER, i.e.
the mailbox notifies itself.

This is deliberately a NOTIFICATION, not an approval channel. Replying to it
does nothing. Approval-by-reply is Phase 2 in docs/automation-and-civic-plan.md
and needs a nonce + sender allowlist to be safe; this module is the half that's
useful on its own and carries no such risk.

Usage:
    python run.py --notify        # after a normal run, or on its own
"""
from __future__ import annotations

import smtplib
import socket
from email.message import EmailMessage
from typing import Optional

from schema import WeeklyReport
from settings import env

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

# A store that renders far below its usual haul is the tell for a broken
# fetcher — call it out rather than let a quiet week look normal.
THIN_STORE_DEALS = 5


def notify_draft_ready(report: WeeklyReport, draft_dir, cfg: dict) -> bool:
    """Email the draft summary. Returns True if sent, False if not configured.

    Never raises: a notification failure must not fail a run that has already
    produced a good draft. The draft is the valuable artifact; the email is a
    convenience on top of it.
    """
    user, pw = env("IMAP_USER"), env("IMAP_APP_PASSWORD")
    to_addr = env("REVIEW_NOTIFY_EMAIL") or user
    if not (user and pw and to_addr):
        print("  ! notify: IMAP_USER / IMAP_APP_PASSWORD / REVIEW_NOTIFY_EMAIL "
              "not set — skipping the review email")
        return False

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to_addr
    msg["Subject"] = _subject(report)
    msg.set_content(_body(report, draft_dir, cfg))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
    except (smtplib.SMTPException, socket.error, OSError) as e:
        print(f"  ! notify: couldn't send the review email ({type(e).__name__}: {e})")
        return False
    print(f"  • notify: review email sent to {to_addr}")
    return True


def _subject(report: WeeklyReport) -> str:
    n = sum(len(s.deals) for s in report.stores)
    return (f"WUM draft ready — week of {report.week_of} "
            f"({n} deals, {len(report.stores)} stores)")


def _body(report: WeeklyReport, draft_dir, cfg: dict) -> str:
    lines = [f"The weekly draft rendered. Nothing is live until you publish it.",
             "", f"Week of {report.week_of}", ""]

    if report.stores:
        lines.append("Stores")
        for s in sorted(report.stores, key=lambda s: -len(s.deals)):
            through = f"  (through {s.valid_through})" if s.valid_through else ""
            flag = "   <-- thin, check the fetcher" if len(s.deals) < THIN_STORE_DEALS else ""
            lines.append(f"  {len(s.deals):3}  {s.name}{through}{flag}")
    else:
        lines.append("Stores: NONE — every fetcher came back empty. Do not publish.")
    lines.append("")

    # Stores configured but absent from the report: the fetcher failed outright.
    missing = _missing_stores(report, cfg)
    if missing:
        lines += ["Missing entirely (fetcher failed or no ad this week):",
                  *(f"  - {m}" for m in missing), ""]

    if report.top_steals:
        lines.append(f"Top steals ({len(report.top_steals)})")
        for t in report.top_steals[:8]:
            price = f"${t.sale_price:.2f}" if t.sale_price is not None else "?"
            lines.append(f"  - {t.item} — {price} @ {t.store}")
        lines.append("")

    if report.events:
        lines.append(f"Events: {len(report.events)}")
        lines.append("")

    low = [d for s in report.stores for d in s.deals if d.confidence == "low"]
    if low:
        lines += [f"Low-confidence reads ({len(low)}) — worth an eyeball:",
                  *(f"  - {d.item}" for d in low[:8]), ""]

    lines += [
        f"Draft: {draft_dir}",
        "",
        "Publish it:",
        "  cd /srv/wum && docker compose run --rm pipeline python run.py --publish",
        "",
        "(Replying to this email does nothing — it's a notification, not an "
        "approval channel.)",
    ]
    return "\n".join(lines)


def _missing_stores(report: WeeklyReport, cfg: dict) -> list[str]:
    """Configured stores with no StoreWeek in the report.

    Matched loosely: the AI names stores from the ad itself, so a configured
    "Yokes" can render as "Yoke's — Broadway". A configured store counts as
    present if any reported name contains it (or vice versa), case/punctuation
    folded.
    """
    def norm(s: str) -> str:
        return "".join(c for c in s.lower() if c.isalnum())

    got = [norm(s.name) for s in report.stores]
    missing = []
    for s in cfg.get("stores", []):
        if not s.get("name"):
            continue
        n = norm(s["name"])
        if not any(n in g or g in n for g in got):
            missing.append(s["name"])
    return missing
