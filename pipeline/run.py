#!/usr/bin/env python3
"""What's Up Missoula — weekly "AI Job" orchestrator.

  python run.py                 # full run: fetch → extract → analyze → render DRAFT
  python run.py --sample        # render the bundled sample report (no email/API)
  python run.py --publish       # promote the current draft → live web root

Review-before-publish: a normal run only produces a DRAFT. After you eyeball it,
run with --publish to push it live.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from settings import load_config
from schema import WeeklyReport

HERE = Path(__file__).resolve().parent


def monday_of_this_week() -> str:
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser(description="What's Up Missoula weekly job")
    ap.add_argument("--sample", action="store_true", help="render bundled sample, no network")
    ap.add_argument("--publish", action="store_true", help="promote draft to live")
    ap.add_argument("--url", help="render a single web flyer URL (testing)")
    ap.add_argument("--store", default="Flyer", help="store name for --url")
    args = ap.parse_args()

    cfg = load_config()
    from render import render  # imported here so --help works without Jinja2

    draft_dir = HERE / cfg["site"]["draft_dir"] / "current"
    live_dir = (HERE / cfg["site"]["output_dir"]).resolve()

    if args.publish:
        from publish import promote
        out = promote(draft_dir, live_dir)
        print(f"Published draft → {out}")
        return 0

    week_of = monday_of_this_week()

    if args.sample:
        report = WeeklyReport.from_dict(json.loads((HERE / "sample_report.json").read_text()))
    elif args.url:
        from web_flyer import render_flyer
        from analyze import analyze
        print(f"Rendering web flyer: {args.url}")
        flyers = render_flyer(args.url, args.store)
        print(f"  → {len(flyers)} image tile(s); analyzing with AI…")
        report = analyze(flyers, week_of, cfg)
    else:
        from email_fetch import fetch_flyer_attachments
        from extract import to_flyer_images
        from analyze import analyze

        work = HERE / ".cache" / week_of
        attachments = fetch_flyer_attachments(cfg, work)
        if not attachments:
            print("No flyer attachments found this week — nothing to do.", file=sys.stderr)
            return 1
        flyers = to_flyer_images(attachments, cfg)
        report = analyze(flyers, week_of, cfg)

    path = render(report, draft_dir)
    print(f"Draft rendered → {path}")
    print("Review it, then run:  python run.py --publish")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
