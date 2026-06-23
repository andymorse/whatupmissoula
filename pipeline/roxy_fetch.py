"""Fetch The Roxy Theater's weekend lineup as structured Event objects.

The Roxy (Missoula's nonprofit community cinema) runs on WordPress with a
custom "gecko-theme" that exposes a clean public REST API — no scraping of the
JS calendar or the Agile ticketing backend needed. Endpoints used:

  • gecko-theme/v1/calendar-events?start_date=&end_date=
        every screening in a date range: title, start/end ISO, start_time,
        show_url, image, + flags (subbed/dubbed/ocap/annex/garden/format).
  • gecko-theme/v1/show-list?page=now-showing|coming-soon
        adds each film's programming `series` (e.g. "New Release",
        "Bleak Week: Cinema of Despair"); joined to calendar rows by show_url.

We pull the upcoming weekend (Fri–Sun of the report week), group screenings by
film, and attach deterministic tags from the feed flags. Kid-friendly /
special-event tagging is AI-assigned later (no rating in the API); see
events_enrich.py.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime, timedelta
from typing import Optional

from schema import Event, Showtime

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


def _get(path: str) -> dict:
    req = urllib.request.Request(f"{BASE}/{path}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _weekend(week_of: str) -> tuple[str, str]:
    """(Friday, Sunday) ISO dates for the report week (Monday-anchored)."""
    monday = date.fromisoformat(week_of)
    friday = monday + timedelta(days=4)
    sunday = monday + timedelta(days=6)
    return friday.isoformat(), sunday.isoformat()


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
    """Return this weekend's Roxy screenings grouped by film."""
    start_date, end_date = _weekend(week_of)
    data = _get(f"calendar-events?start_date={start_date}&end_date={end_date}")
    rows = data.get("events", [])
    series_map = _series_by_url("now-showing", "coming-soon")

    by_film: dict[str, Event] = {}
    order: list[str] = []
    for r in rows:
        if r.get("allDay"):
            # All-day rows are festival/holds, not a single screening time.
            continue
        key = r.get("show_url") or r.get("title", "")
        if not key:
            continue
        if key not in by_film:
            ev = Event(
                title=r.get("title", "").strip(),
                url=r.get("show_url"),
                image=r.get("image"),
                series=series_map.get(r.get("show_url", "")),
                runtime_min=_runtime_min(r.get("start"), r.get("end")),
                tags=[label for flag, label in _FLAG_TAGS.items() if r.get(flag)],
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
    # Anchor to Monday so the weekend window matches a normal run.
    mon = date.fromisoformat(week)
    mon = (mon - timedelta(days=mon.weekday())).isoformat()
    events = fetch_roxy_events(mon)
    print(f"Weekend of {mon}: {len(events)} film(s)\n")
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
