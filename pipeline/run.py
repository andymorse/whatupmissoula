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
    ap.add_argument("--images", help="analyze flyer image(s)/PDF(s) from a file or folder")
    ap.add_argument("--store", default=None,
                    help="store name for --url, or default store for --images")
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
        flyers = render_flyer(args.url, args.store or "Flyer")
        print(f"  → {len(flyers)} image tile(s); analyzing with AI…")
        report = analyze(flyers, week_of, cfg)
    elif args.images:
        from extract import gather_flyer_files, to_flyer_images_pairs
        from analyze import analyze
        pairs = gather_flyer_files(args.images, args.store)
        if not pairs:
            print(f"No image/PDF flyers found at {args.images}", file=sys.stderr)
            return 1
        stores = sorted({h for _, h in pairs})
        print(f"Found {len(pairs)} flyer file(s) across {len(stores)} store(s): {', '.join(stores)}")
        flyers = to_flyer_images_pairs(pairs, cfg)
        print(f"  → {len(flyers)} image tile(s); analyzing with AI…")
        report = analyze(flyers, week_of, cfg)
    else:
        # Default weekly path: fetch flyer emails → render each linked ad → analyze.
        from email_fetch import fetch_flyer_emails
        from web_flyer import render_flyer
        from analyze import analyze

        emails = fetch_flyer_emails(cfg)
        if not emails:
            print("No flyer emails found this week — nothing to do.", file=sys.stderr)
            return 1
        print(f"Found {len(emails)} flyer email(s):")
        flyers = []
        for fe in emails:
            if not fe.flyer_url:
                print(f"  ! {fe.store}: no flyer link found in email — skipping", file=sys.stderr)
                continue
            print(f"  • {fe.store}: rendering {fe.flyer_url[:70]}…")
            try:
                flyers += render_flyer(fe.flyer_url, fe.store)
            except Exception as e:                 # one blocked store shouldn't sink the run
                print(f"  ! {fe.store}: render failed ({e}) — skipping", file=sys.stderr)
        if not flyers:
            print("Could not render any flyer this week — nothing to do.", file=sys.stderr)
            return 1
        print(f"  → {len(flyers)} image tile(s); analyzing with AI…")
        report = analyze(flyers, week_of, cfg)

    path = render(report, draft_dir)
    print(f"Draft rendered → {path}")
    print("Review it, then run:  python run.py --publish")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
