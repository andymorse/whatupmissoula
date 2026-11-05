"""Fetch the Missoula Public Library's programs as Event objects.

The library's site runs the Modern Events Calendar (MEC) WordPress plugin,
which publishes the whole program calendar as a public iCal feed:

    https://www.missoulapubliclibrary.org/?mec-ical-feed=1

Each VEVENT carries title, start/end, description, image (ATTACH), link, and
CATEGORIES that mix audience ("Youth 0–5", "Teens", "All Ages"), program type
("Story Times & Early Literacy", "Classes & Workshops") and branch. Recurring
programs (Story Time, clubs) come as one VEVENT with an RRULE plus EXDATEs for
skipped dates, so we expand them with dateutil.

Kid / special tags come straight from the library's own categories — no AI.
We keep the report week (Wednesday → the following Tuesday, same window the
rest of the events page uses) and fold repeats of a program into one card.
"""
from __future__ import annotations

import re
import urllib.request
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr

from schema import Event, Showtime
from url_guard import safe_url

VENUE = "Missoula Public Library"
FEED = "https://www.missoulapubliclibrary.org/?mec-ical-feed=1"
TZ = ZoneInfo("America/Denver")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_KIDS = {"Youth 0–5", "Youth 6–12", "Families First", "Story Times & Early Literacy"}
_SPECIAL = {"Special Events & Exhibits"}
_AUDIENCE = {"Youth 0–5": "Ages 0–5", "Youth 6–12": "Ages 6–12",
             "Teens": "Teens", "Adults": "Adults", "All Ages": "All ages"}
# Categories that say where/who-with rather than what — never shown as the type.
_NOT_TYPE = set(_AUDIENCE) | {"Downtown Library", "Branch Libraries",
                              "External Partner", "Families First"}


def _unescape(v: str) -> str:
    v = v.replace("\\n", "\n").replace("\\N", "\n")
    v = re.sub(r"\\([,;\\])", r"\1", v)
    return v.replace("&amp;", "&").strip()


def _parse_ics(text: str) -> list[dict]:
    """Minimal VEVENT reader: {NAME: [(params, value), …]} per event."""
    text = re.sub(r"\r?\n[ \t]", "", text)          # unfold continuation lines
    events, cur = [], None
    for line in text.splitlines():
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT" and cur is not None:
            events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, value = line.split(":", 1)
            name, *params = head.split(";")
            cur.setdefault(name.upper(), []).append((params, value))
    return events


def _first(ev: dict, name: str) -> str | None:
    return ev[name][0][1] if name in ev else None


def _dt(params: list[str], value: str) -> datetime:
    """DTSTART/EXDATE value → aware datetime (all-day dates → local midnight)."""
    if "VALUE=DATE" in params or len(value) == 8:
        return datetime.combine(date(int(value[:4]), int(value[4:6]), int(value[6:8])),
                                time(), TZ)
    tz = next((ZoneInfo(p[5:]) for p in params if p.startswith("TZID=")), None)
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=ZoneInfo("UTC")).astimezone(TZ)
    return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=tz or TZ)


def _occurrences(ev: dict, start: datetime, end: datetime) -> list[datetime]:
    """Every start time of this VEVENT inside [start, end)."""
    params, value = ev["DTSTART"][0]
    dtstart = _dt(params, value)
    rule = _first(ev, "RRULE")
    if not rule:
        return [dtstart] if start <= dtstart < end else []
    skip_dates = set()
    for params, value in ev.get("EXDATE", []):
        for v in value.split(","):
            skip_dates.add(_dt(params, v).date())
    return [o for o in rrulestr(rule, dtstart=dtstart).between(start, end, inc=True)
            if o.date() not in skip_dates and o < end]


def _trim(text: str, limit: int = 220) -> str | None:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text or None
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def _offsite(location: str | None) -> str | None:
    """Where it is, if not the downtown library (branches, partners, virtual)."""
    if not location or "455 E. Main" in location:
        return None
    return location.strip()


def _fetch(url: str) -> str:
    req = urllib.request.Request(safe_url(url), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def fetch_library_events(week_of: str, feed: str = FEED) -> list[Event]:
    monday = date.fromisoformat(week_of)
    start = datetime.combine(monday + timedelta(days=2), time(), TZ)   # Wednesday
    end = start + timedelta(days=7)

    by_key: dict[tuple, Event] = {}
    firsts: dict[tuple, datetime] = {}
    for ev in _parse_ics(_fetch(feed)):
        if "DTSTART" not in ev or not _first(ev, "SUMMARY"):
            continue
        when = sorted(_occurrences(ev, start, end))
        if not when:
            continue
        title = _unescape(_first(ev, "SUMMARY"))
        url = _first(ev, "URL")
        cats = [_unescape(c) for c in (_first(ev, "CATEGORIES") or "").split(",") if c.strip()]
        all_day = len(ev["DTSTART"][0][1]) == 8
        shows = [Showtime(date=o.date().isoformat(), day=o.strftime("%a"),
                          time="All day" if all_day else o.strftime("%-I:%M %p"))
                 for o in when]

        key = (title.lower(), url)
        if key in by_key:                    # same program listed twice → merge dates
            seen = {(s.date, s.time) for s in by_key[key].showtimes}
            by_key[key].showtimes += [s for s in shows if (s.date, s.time) not in seen]
            by_key[key].showtimes.sort(key=lambda s: (s.date, s.time))
            firsts[key] = min(firsts[key], when[0])
            continue

        tags = []
        if _KIDS & set(cats):
            tags.append("kid-friendly")
        if _SPECIAL & set(cats):
            tags.append("special-event")
        tags += [_AUDIENCE[c] for c in cats if c in _AUDIENCE]
        where = _offsite(_unescape(_first(ev, "LOCATION") or ""))
        if where == "Virtual Event":
            tags.append("Virtual")
        desc = _trim(_unescape(_first(ev, "DESCRIPTION") or ""))
        if where and where != "Virtual Event":
            desc = f"At {where}." + (f" {desc}" if desc else "")

        by_key[key] = Event(
            title=title,
            venue=VENUE,
            url=url,
            image=_first(ev, "ATTACH"),
            series=next((c for c in cats if c not in _NOT_TYPE), None),
            showtimes=shows,
            tags=tags,
            note=desc,
        )
        firsts[key] = when[0]

    return [by_key[k] for k in sorted(by_key, key=lambda k: firsts[k])]


if __name__ == "__main__":
    # Smoke test: this week's library programs (network, no AI).
    from run import monday_of_this_week

    evs = fetch_library_events(monday_of_this_week())
    print(f"{len(evs)} program(s)")
    for e in evs:
        slots = ", ".join(f"{s.day} {s.time}" for s in e.showtimes)
        print(f"  {e.title}  [{e.series}]  {slots}  {e.tags}")
