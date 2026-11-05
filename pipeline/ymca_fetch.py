"""Fetch the Missoula Family YMCA's schedule for the /ymca/ page.

The Y's own schedule (ymcamissoula.org/schedules) is a Daxko widget framed from
members.daxko.com. Its JSON API wants a key, but the widget's public "Print
Schedule" button serves a plain PDF of one full week — every area, no login:

    members.daxko.com/schedules/<site>/printSchedule?branchId=…&startDate=MM/DD/YYYY

That PDF is a 7-column grid (one column per day). `pdftotext -bbox-layout`
(poppler, already in the image) hands back each class as a positioned text
block: title (may wrap), area, optional instructor, then the time. We assign
each block to the nearest day column and sort it into a section. No AI, no
browser — so it's free to refresh on every render.
"""
from __future__ import annotations

import html
import re
import subprocess
import tempfile
import urllib.request
from datetime import date, timedelta

from url_guard import safe_url

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
PRINT_URL = ("https://members.daxko.com/schedules/{site}/printSchedule"
             "?branchId={branch}&startDate={start:%m/%d/%Y}&areaIds=")

# Areas as the Y names them in the widget's Area filter. Used to tell a wrapped
# title from the area line beneath it ("Lap Swim - Whole" / "Pool" / "Pool").
AREAS = {
    "Airnasium", "Big Gym", "Child Watch", "Climbing Wall", "Cycling Studio",
    "Functional Training Room", "Group Exercise Studio",
    "Missoula Public Library", "Pool", "Squash Court 1 (North)",
    "Squash Court 2 (South)", "Sunrise Studio", "Sunset Studio", "The Commons",
    "Track", "Water Fitness", "Youth Activity Center (YAC)", "Youth Gym",
}

# Page sections, in display order.
SECTIONS = ["Pool", "Classes", "Kids & Family", "Climb", "Gym & Courts"]
_KIDS_WORDS = ("family", "kid", "rookie", "teen", "youth", "little", "junior",
               "game room", "child watch", "parents night", "active 6")
_GYM_AREAS = {"Big Gym", "Airnasium", "Track", "The Commons",
              "Squash Court 1 (North)", "Squash Court 2 (South)"}

_TIME_RE = re.compile(r"^(\d{1,2}(?::\d\d)?\s*[ap]m)\s*-\s*(\d{1,2}(?::\d\d)?\s*[ap]m)$", re.I)
_DAY_RE = re.compile(r"^(MON|TUE|WED|THU|FRI|SAT|SUN) (\d{1,2})$")
_BLOCK_RE = re.compile(
    r'<block xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</block>', re.S)


def _minutes(t: str) -> int:
    """'5:30am' → 330, '12pm' → 720."""
    m = re.match(r"(\d{1,2})(?::(\d\d))?\s*([ap])m", t.strip(), re.I)
    h, mm, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
    return (h % 12 + (12 if ap == "p" else 0)) * 60 + mm


def _pretty_time(mins: int) -> str:
    """330 → '5:30', 720 → '12:00' — the am/pm goes on the range, not each end."""
    h = mins // 60 % 12 or 12
    return f"{h}:{mins % 60:02d}"


def _range(start: int, end: int) -> str:
    """'5:30–7:00a', '11:30a–12:30p' — compact, like a printed schedule."""
    sa, ea = ("a" if start < 720 else "p"), ("a" if end < 720 else "p")
    if sa == ea:
        return f"{_pretty_time(start)}–{_pretty_time(end)}{ea}"
    return f"{_pretty_time(start)}{sa}–{_pretty_time(end)}{ea}"


def _split(lines: list[str]) -> tuple[str, str | None, str | None]:
    """Block lines (time already removed) → (title, area, instructor).

    Take the *last* run of lines that spells a known area, so a title that
    happens to end in an area word keeps it: ["Lap Swim - Whole", "Pool",
    "Pool"] → title "Lap Swim - Whole Pool", area "Pool".
    """
    best = None
    for i in range(1, len(lines)):
        for j in range(i + 1, len(lines) + 1):
            if " ".join(lines[i:j]) in AREAS:
                best = (i, j)
    if not best:
        return " ".join(lines), None, None
    i, j = best
    rest = " ".join(lines[j:]) or None
    return " ".join(lines[:i]), " ".join(lines[i:j]), rest


def _section(title: str, area: str | None) -> str:
    t = title.lower()
    if any(w in t for w in _KIDS_WORDS) or area in {"Youth Gym", "Youth Activity Center (YAC)", "Child Watch"}:
        return "Kids & Family"
    if area in {"Pool", "Water Fitness"}:
        return "Pool"
    if area == "Climbing Wall" or "climb" in t:
        return "Climb"
    if area in _GYM_AREAS:
        return "Gym & Courts"
    return "Classes"


def _parse_week(bbox_html: str, start: date) -> dict[str, list[dict]]:
    """bbox XHTML for one weekly PDF → {iso_date: [item, …]}."""
    out: dict[str, list[dict]] = {}
    for page in bbox_html.split("<page ")[1:]:
        blocks = []
        for x0, y0, x1, _y1, body in _BLOCK_RE.findall(page):
            lines = [html.unescape(" ".join(re.findall(r">([^<]+)</word>", ln)))
                     for ln in re.findall(r"<line.*?</line>", body, re.S)]
            blocks.append(((float(x0) + float(x1)) / 2, float(y0), lines))
        # Day headers ("THU 5") give each column's centre, left to right.
        cols = sorted(x for x, _, ls in blocks if len(ls) == 1 and _DAY_RE.match(ls[0]))
        if len(cols) != 7:
            continue                       # not a schedule page
        for x, _y, lines in blocks:
            if len(lines) < 2 or not _TIME_RE.match(lines[-1]):
                continue                   # headers, hour labels, footer
            col = min(range(7), key=lambda k: abs(cols[k] - x))
            m = _TIME_RE.match(lines[-1])
            title, area, who = _split(lines[:-1])
            if not title:
                continue
            # "Closed" / "Reserved For YMCA Active 6": the space isn't open to
            # members then — shown greyed so a gap in the day makes sense.
            closed = bool(re.match(r"(closed|reserved)\b", title, re.I))
            cancelled = bool(re.search(r"cancel", f"{title} {who or ''}", re.I))
            if who and (who == area or re.search(r"cancel|closed|no class|rotation|to be announced", who, re.I)):
                who = None                 # status text / placeholder, not a name
            s, e = _minutes(m.group(1)), _minutes(m.group(2))
            out.setdefault((start + timedelta(days=col)).isoformat(), []).append({
                # "Open Climb- Adults Only" → "Open Climb - Adults Only"
                "title": re.sub(r"(\w)- ", r"\1 - ",
                                re.sub(r"^CANCELLED:\s*", "", title, flags=re.I)),
                "area": area,
                "instructor": who,
                "start": s,
                "end": e,
                "time": _range(s, e),
                "section": _section(title, area),
                "closed": closed,
                "cancelled": cancelled,
            })
    return out


def _fetch_pdf(url: str) -> bytes:
    req = urllib.request.Request(safe_url(url), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    if not data.startswith(b"%PDF"):
        raise ValueError("print schedule didn't return a PDF")
    return data


def fetch_ymca_schedule(cfg: dict, today: date | None = None) -> dict:
    """Return {"days": [...], "source": url} covering `weeks` weeks from today."""
    ycfg = cfg.get("ymca") or {}
    site, branch = ycfg["daxko_site"], ycfg["branch_id"]
    today = today or date.today()
    by_day: dict[str, list[dict]] = {}
    for w in range(int(ycfg.get("weeks", 2))):
        start = today + timedelta(days=7 * w)
        pdf = _fetch_pdf(PRINT_URL.format(site=site, branch=branch, start=start))
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(pdf)
            f.flush()
            bbox = subprocess.run(["pdftotext", "-bbox-layout", f.name, "-"],
                                  capture_output=True, text=True, check=True).stdout
        by_day.update(_parse_week(bbox, start))
    if not by_day:
        raise ValueError("no schedule items parsed — has the print layout changed?")

    days = []
    for iso in sorted(by_day):
        d = date.fromisoformat(iso)
        items = sorted(by_day[iso], key=lambda i: (i["start"], i["end"], i["title"]))
        days.append({
            "date": iso,
            "label": f"{d:%A}, {d:%b} {d.day}",
            "sections": [{"name": s, "items": [i for i in items if i["section"] == s]}
                         for s in SECTIONS if any(i["section"] == s for i in items)],
        })
    return {"days": days, "source": ycfg.get("url", "https://www.ymcamissoula.org/schedules")}
