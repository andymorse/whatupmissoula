"""Build the /regulars/ page data: local places with a steady weekly schedule.

Two kinds of entry in config.yaml `regulars:` (listed in display order):

  • schedule_page: ymca — a big, fetched schedule with its own page
    (/regulars/ymca/, see ymca_fetch.py). The card just links to it.
  • items: [...] — a fixed weekly lineup typed in by hand, for places with no
    machine-readable calendar. Draught Works Brewery is the first: their site
    has no events feed (their /events/ page embeds missoulaevents.net), but
    /events/recurring-events/ publishes a stable weekly schedule in plain text.
    No network and no AI: nothing here breaks when someone else's HTML
    changes; the only upkeep is editing config when the venue changes it.

Item fields:

    - title: "Sunday Night Jazz"
      weekday: "Sunday"       # full day name, or a list of them
      time: "6:00 PM"         # display string, or "All day"
      weeks: [1]              # optional: which weeks of the month it runs
      tags: ["Live music"]
      series: "First Thursday"
      note: "Bring your own records."

`weeks` is how a monthly slot coexists with a weekly one on the same weekday
("first Thursday" = week [1]; weeks are counted by day-of-month, 1st–7th = 1).
"""
from __future__ import annotations

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]
_ORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}


def _days(raw) -> list[int]:
    names = raw if isinstance(raw, list) else [raw]
    idx = {d.lower(): i for i, d in enumerate(_WEEKDAYS)}
    return sorted({idx[str(n).strip().lower()] for n in names
                   if n and str(n).strip().lower() in idx})


def _when(days: list[int], weeks) -> str:
    """[3, 5] → 'Thursdays & Saturdays'; [3] + weeks [1] → '1st Thursday'."""
    if weeks:
        ords = " & ".join(_ORD.get(w, f"{w}th") for w in sorted(weeks))
        return f"{ords} {' & '.join(_WEEKDAYS[d] for d in days)}"
    if len(days) == 7:
        return "Every day"
    plural = [_WEEKDAYS[d] + "s" for d in days]
    return plural[0] if len(plural) == 1 else ", ".join(plural[:-1]) + " & " + plural[-1]


def build_regulars(cfg: dict) -> list[dict]:
    """Config → cards for the template: name, url, blurb, page or rows."""
    cards = []
    for r in cfg.get("regulars") or []:
        if not r.get("name"):
            continue
        rows = []
        for item in r.get("items") or []:
            days = _days(item.get("weekday"))
            if not item.get("title") or not days:
                continue
            rows.append({
                "when": _when(days, item.get("weeks")),
                "time": str(item.get("time") or "All day"),
                "title": item["title"],
                "series": item.get("series"),
                "tags": list(item.get("tags") or []),
                "note": item.get("note"),
                "_sort": (days[0], 0 if not item.get("weeks") else 1),
            })
        rows.sort(key=lambda x: x.pop("_sort"))
        cards.append({
            "name": r["name"],
            "url": r.get("url"),
            "blurb": r.get("blurb"),
            "page": r.get("schedule_page"),
            "rows": rows,
        })
    return cards


if __name__ == "__main__":
    from settings import load_config

    for c in build_regulars(load_config()):
        print(c["name"], f"→ /regulars/{c['page']}/" if c["page"] else "")
        for row in c["rows"]:
            print(f"   {row['when']:<28} {row['time']:<8} {row['title']}")
