"""Fetch The Roxy Theater's weekly lineup as structured Event objects.

The Roxy (Missoula's nonprofit community cinema) runs on WordPress with a
custom "gecko-theme" that exposes a clean public REST API — no scraping of the
JS calendar or the Agile ticketing backend needed. Endpoints used:

  • gecko-theme/v1/calendar-events?start_date=&end_date=
        every screening in a date range: title, start/end ISO, start_time,
        show_url, image, + flags (subbed/dubbed/ocap/annex/garden/format).
  • gecko-theme/v1/show-list?page=now-showing|coming-soon
        adds each film's programming `series` (e.g. "New Release",
        "Bleak Week: Cinema of Despair"); joined to calendar rows by show_url.

We pull the full report week (Wednesday → the following Tuesday, matching the
deals' Wednesday-to-Wednesday cadence), group screenings by film, and attach
tags. Many tags are deterministic from the Roxy's own programming `series`
("Roxy Jr." → kids; "With Special Guest…", festivals, free screenings →
special events) plus the feed's format flags. AI fills the gaps for films the
series doesn't make obvious (see events_enrich.py) — the API has no rating.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime, timedelta
from typing import Optional

from schema import Event, Showtime
from url_guard import safe_url

BASE = "https://www.theroxytheater.org/wp-json/gecko-theme/v1"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# Feed flag -> human badge. These ride along into the page's search index too.
_FLAG_TAGS = {
    "subbed": "Subtitled",
    "dubbed": "Dubbed",
    "ocap": "Open caption",
    "garden": "Garden screening",
    "annex": "Annex",
}

# Words in a programming `series` that mark a one-off / curated special event
# (guest appearances, festivals, free community screenings, live comedy, etc.).
# Genre repertory series (Bleak Week, Cinema Abroad, …) deliberately don't match
# — they're regular themed programming, not special events.
_SPECIAL_SERIES_HINTS = (
    "special", "guest", "festival", "presents", "free", "comedy", "live",
    "discussion", "engagement", "mtff", "doc film", "celebration",
    "workshop", "salon",
)


def _series_tags(series: Optional[str]) -> list[str]:
    """Deterministic tags from the Roxy's own series label."""
    if not series:
        return []
    s = series.lower()
    tags: list[str] = []
    if "roxy jr" in s:                                   # the Roxy's kids/family series
        tags.append("kid-friendly")
    if any(h in s for h in _SPECIAL_SERIES_HINTS):
        tags.append("special-event")
    return tags


def _get(path: str) -> dict:
    url = safe_url(f"{BASE}/{path}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _week_window(week_of: str) -> tuple[str, str]:
    """(Wednesday, following Tuesday) — the Wed→Wed week matching the deals cadence.

    week_of is the Monday anchor; the site refreshes Wednesdays, so we show that
    Wednesday through the day before the next refresh (a full, non-overlapping week).
    """
    monday = date.fromisoformat(week_of)
    wednesday = monday + timedelta(days=2)
    next_tuesday = monday + timedelta(days=8)
    return wednesday.isoformat(), next_tuesday.isoformat()


def _series_by_url(*pages: str) -> dict[str, str]:
    """Map show permalink -> programming series from the show-list endpoint."""
    out: dict[str, str] = {}
    for page in pages:
        try:
            data = _get(f"show-list?page={page}")
        except Exception:
            continue
        for s in data.get("shows", []):
            url = s.get("permalink") or s.get("show_url")
            if url and s.get("series"):
                out[url] = s["series"]
    return out


def _runtime_min(start: Optional[str], end: Optional[str]) -> Optional[int]:
    if not start or not end:
        return None
    try:
        delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
        mins = int(delta.total_seconds() // 60)
        return mins if mins > 0 else None
    except ValueError:
        return None


def _fmt_time(start: str, fallback: str) -> str:
    """'2026-06-26T14:00:00-05:00' -> '2:00 PM'. Fall back to the feed string."""
    try:
        dt = datetime.fromisoformat(start)
        return dt.strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return fallback


def fetch_roxy_events(week_of: str) -> list[Event]:
    """Return this week's Roxy screenings (Wed→Tue) grouped by film."""
    start_date, end_date = _week_window(week_of)
    data = _get(f"calendar-events?start_date={start_date}&end_date={end_date}")
    rows = data.get("events", [])
    series_map = _series_by_url("now-showing", "coming-soon")

    by_film: dict[str, Event] = {}
    order: list[str] = []
    for r in rows:
        if r.get("allDay"):
            # All-day rows are festival passes/holds, not a single screening time.
            continue
        key = r.get("show_url") or r.get("title", "")
        if not key:
            continue
        if key not in by_film:
            series = series_map.get(r.get("show_url", ""))
            flag_tags = [label for flag, label in _FLAG_TAGS.items() if r.get(flag)]
            ev = Event(
                title=r.get("title", "").strip(),
                url=r.get("show_url"),
                image=r.get("image"),
                series=series,
                runtime_min=_runtime_min(r.get("start"), r.get("end")),
                # kid/special (from series) first, then format flags; deduped.
                tags=list(dict.fromkeys(_series_tags(series) + flag_tags)),
            )
            by_film[key] = ev
            order.append(key)
        ev = by_film[key]
        start = r.get("start", "")
        d = start[:10] if start else ""
        try:
            day = datetime.fromisoformat(start).strftime("%a") if start else ""
        except ValueError:
            day = ""
        ev.showtimes.append(Showtime(
            date=d,
            day=day,
            time=_fmt_time(start, r.get("start_time", "")),
            event_id=r.get("event_id"),
        ))

    return [by_film[k] for k in order]


if __name__ == "__main__":
    import sys
    week = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    # Anchor to Monday so the week window matches a normal run.
    mon = date.fromisoformat(week)
    mon = (mon - timedelta(days=mon.weekday())).isoformat()
    events = fetch_roxy_events(mon)
    print(f"Week of {mon} (Wed→Tue): {len(events)} film(s)\n")
    for e in events:
        times = ", ".join(f"{s.day} {s.time}" for s in e.showtimes)
        bits = [e.title]
        if e.series:
            bits.append(f"[{e.series}]")
        if e.runtime_min:
            bits.append(f"{e.runtime_min}min")
        if e.tags:
            bits.append("tags=" + ",".join(e.tags))
        print("  • " + " ".join(bits))
        print(f"      {times}")
