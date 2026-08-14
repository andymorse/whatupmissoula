"""Materialize a venue's published recurring schedule into Event objects.

Some venues have no machine-readable calendar to fetch. Draught Works Brewery is
the first: their site is WordPress with no events post type and no feed, and
their own /events/ page just embeds a third-party board (missoulaevents.net) —
so even the venue doesn't own the data. What they *do* publish, in plain text on
/events/recurring-events/, is a stable weekly schedule. We generate it locally.

No network and no AI: nothing here can break when someone else's HTML changes,
and the only maintenance is editing config when the venue changes its schedule.
The tradeoff is that we get the slot, not the specific act — "Live Music on the
Murphy Stage, Thursday 7 PM", not which band is playing. Each venue carries a
`note` pointing readers at the venue's own listing for that detail.

Config lives under `events.recurring` in config.yaml:

    events:
      recurring:
        - venue: "Draught Works Brewery"
          url: "https://www.draughtworksbrewery.com/events/"
          note: "Weekly lineup changes — check their listing for who's playing."
          items:
            - title: "Sunday Night Jazz"
              weekday: "Sunday"       # full day name, or a list of them
              time: "6:00 PM"         # display string, or "All day"
              tags: ["Live music"]
              weeks: [1, 2, 3, 4, 5]  # optional: which weeks of the month it runs

`weeks` is how a monthly item coexists with a weekly one on the same weekday —
Draught Works runs live music every Thursday *except* the first, which is Vinyl
Night, so live music is weeks [2,3,4,5] and Vinyl Night is week [1]. Weeks are
counted by day-of-month (1st–7th = week 1, 8th–14th = week 2, …), which is how
venues actually mean "first Thursday".
"""
from __future__ import annotations

from datetime import date, timedelta

from schema import Event, Showtime

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def fetch_recurring_events(cfg: dict, week_of: str) -> list[Event]:
    """Build Events for every configured recurring item falling in this week."""
    venues = (cfg.get("events") or {}).get("recurring") or []
    days = _week_days(week_of)
    events: list[Event] = []
    for venue in venues:
        name = venue.get("venue")
        if not name:
            continue
        for item in venue.get("items") or []:
            ev = _materialize(item, venue, name, days)
            if ev:
                events.append(ev)
    return events


def _materialize(item: dict, venue: dict, venue_name: str,
                 days: list[date]) -> Event | None:
    """One recurring item -> an Event with a showtime per matching day, or None."""
    title = item.get("title")
    raw = item.get("weekday")
    names = raw if isinstance(raw, list) else [raw]
    wds = {_WEEKDAYS[n] for n in
           (str(x).strip().lower() for x in names if x) if n in _WEEKDAYS}
    if not title or not wds:
        return None
    weeks = item.get("weeks")  # None => every week
    time_label = str(item.get("time") or "All day")

    showtimes = [
        Showtime(date=d.isoformat(), day=d.strftime("%a"), time=time_label)
        for d in days
        if d.weekday() in wds and (weeks is None or _week_of_month(d) in weeks)
    ]
    if not showtimes:
        return None

    return Event(
        title=title,
        venue=venue_name,
        url=item.get("url") or venue.get("url"),
        image=None,
        series=item.get("series"),
        runtime_min=None,
        showtimes=showtimes,
        tags=list(item.get("tags") or []),
        note=item.get("note") or venue.get("note"),
    )


def _week_days(week_of: str) -> list[date]:
    """The seven dates of the report week (Wednesday → the following Tuesday).

    Mirrors roxy_fetch._week_window so both sources cover the same span: week_of
    is the Monday anchor, and the site refreshes Wednesdays.
    """
    monday = date.fromisoformat(week_of)
    wednesday = monday + timedelta(days=2)
    return [wednesday + timedelta(days=i) for i in range(7)]


def _week_of_month(d: date) -> int:
    """1 for the 1st–7th, 2 for the 8th–14th, and so on — 'the first Thursday'."""
    return (d.day - 1) // 7 + 1


if __name__ == "__main__":
    # Smoke test: print this week's generated recurring events (no network).
    from settings import load_config
    from run import monday_of_this_week

    cfg = load_config()
    week_of = monday_of_this_week()
    days = _week_days(week_of)
    print(f"week_of={week_of}  window={days[0]} → {days[-1]}\n")
    evs = fetch_recurring_events(cfg, week_of)
    if not evs:
        print("No recurring events configured (events.recurring).")
    for e in evs:
        slots = ", ".join(f"{s.day} {s.date} {s.time}" for s in e.showtimes)
        print(f"  {e.title}  [{e.venue}]")
        print(f"     {slots}")
        if e.tags:
            print(f"     tags: {', '.join(e.tags)}")
