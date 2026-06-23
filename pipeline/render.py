"""Render a WeeklyReport into a static HTML site using Jinja2.

Output is plain files (index.html + copied static assets) — no runtime, nothing
to attack. Renders into a target directory (draft or live).
"""
from __future__ import annotations

import json
import shutil
from datetime import date as _date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from schema import WeeklyReport


def _pretty_date(iso: str | None) -> str:
    """'2026-06-09' → 'Jun 9'. Pass through anything that isn't an ISO date."""
    if not iso:
        return ""
    try:
        d = _date.fromisoformat(iso)
    except (ValueError, TypeError):
        return iso
    return f"{d:%b} {d.day}"

HERE = Path(__file__).resolve().parent
SITE = HERE.parent / "site"
TEMPLATES = SITE / "templates"
STATIC = SITE / "static"
ROOT_ASSETS = SITE / "root"  # files served from the site root (favicons, manifest)


TOP_STEALS_TARGET = 12  # page shows Top Steals in a 4-up grid; 12 = 3 full rows


def _cap_top_steals(report: WeeklyReport) -> None:
    """Trim Top Steals to a full grid so the last row is never ragged.

    Guidance asks the model for at least TOP_STEALS_TARGET; we keep that many when
    available, else fall back to the largest complete row of 4. Run after
    _curate_order, which has already floated editor's picks / WUM recommendations
    to the front — so trimming only ever drops the lowest-value extras.
    """
    n = len(report.top_steals)
    if n >= TOP_STEALS_TARGET:
        keep = TOP_STEALS_TARGET
    elif n >= 4:
        keep = (n // 4) * 4
    else:
        keep = n
    report.top_steals = report.top_steals[:keep]


def _curate_rank(item) -> int:
    """Sort key: the owner's Editor's picks first, WUM Recommendations next,
    everything else last.

    `watchlist_source == "mine"` is the owner's hand-picked list; `"ai"` are the
    household staples we surface as a "WUM Recommendation." A stable sort keeps
    the underlying value order intact *within* each group, so we reorder by
    curation without scrambling the ranking.
    """
    if not item.watchlist_hit:
        return 2
    return {"mine": 0, "ai": 1}.get(item.watchlist_source, 1)


def _curate_order(report: WeeklyReport) -> None:
    """Float curated items to the top — of Top Steals and of each store table.

    Editor's picks (the owner's own list) come first, then WUM Recommendations
    (household staples), then everything else in value order (see ai/guidance.md
    §6). Done here deterministically rather than asking the model to also own
    presentation order.
    """
    report.top_steals.sort(key=_curate_rank)
    for store in report.stores:
        store.deals.sort(key=_curate_rank)


def render(report: WeeklyReport, out_dir: str | Path) -> Path:
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    _curate_order(report)
    _cap_top_steals(report)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    env.filters["prettydate"] = _pretty_date

    # Map store name → its ad's through-date so each top-steal can show an expiry
    # (the date lives on the StoreWeek, not the TopSteal — single source of truth).
    store_dates = {s.name: s.valid_through for s in report.stores if s.valid_through}
    html = env.get_template("index.html.j2").render(report=report, store_dates=store_dates)
    (out / "index.html").write_text(html, encoding="utf-8")

    # Events page → /events/index.html (served at /events/). Same report, same
    # shared assets (absolute /static paths work from the subdir).
    events_html = env.get_template("events.html.j2").render(report=report)
    events_dir = out / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    (events_dir / "index.html").write_text(events_html, encoding="utf-8")

    # Copy static assets (css, images) into the output tree.
    dest_static = out / "static"
    if dest_static.exists():
        shutil.rmtree(dest_static)
    shutil.copytree(STATIC, dest_static)

    # Copy root-served assets (favicons, webmanifest) to the output root so
    # browsers find /favicon.ico, /apple-touch-icon.png, /site.webmanifest, etc.
    if ROOT_ASSETS.is_dir():
        for asset in ROOT_ASSETS.iterdir():
            if asset.is_file():
                shutil.copy2(asset, out / asset.name)

    # Keep the machine-readable report alongside the page (handy + future API).
    (out / "report.json").write_text(
        json.dumps(report.to_dict(), indent=2), encoding="utf-8"
    )
    return out / "index.html"


if __name__ == "__main__":
    # Quick preview: render the bundled sample report so the look is visible
    # without needing email/API access.
    sample = json.loads((HERE / "sample_report.json").read_text())
    path = render(WeeklyReport.from_dict(sample), HERE / "drafts" / "preview")
    print(f"Rendered preview → {path}")
