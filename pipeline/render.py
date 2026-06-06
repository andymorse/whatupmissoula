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


def _watch_rank(source: str | None) -> int:
    """Sort key: owner's picks first, AI staples next, everything else last.

    Stable sorting on this key keeps the AI's value ranking intact *within* each
    group, so we reorder by curation without scrambling the underlying ranking.
    """
    return {"mine": 0, "ai": 1}.get(source, 2)


def _curate_order(report: WeeklyReport) -> None:
    """Float editor's picks to the top — of Top Steals and of each store table.

    The AI returns both lists in value order; the site owner wants their own
    picks called out first (see ai/guidance.md §6). We do it here, deterministically,
    rather than asking the model to also own presentation order.
    """
    report.top_steals.sort(key=lambda s: _watch_rank(s.watchlist_source if s.watchlist_hit else None))
    for store in report.stores:
        store.deals.sort(key=lambda d: _watch_rank(d.watchlist_source if d.watchlist_hit else None))


def render(report: WeeklyReport, out_dir: str | Path) -> Path:
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    _curate_order(report)

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

    # Copy static assets (css, images) into the output tree.
    dest_static = out / "static"
    if dest_static.exists():
        shutil.rmtree(dest_static)
    shutil.copytree(STATIC, dest_static)

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
