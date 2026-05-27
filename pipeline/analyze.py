"""Tie the guidance doc + flyer images to a provider, return a WeeklyReport."""
from __future__ import annotations

from pathlib import Path

from providers.base import FlyerImage, get_provider
from schema import WeeklyReport
from settings import env

HERE = Path(__file__).resolve().parent


def analyze(flyers: list[FlyerImage], week_of: str, cfg: dict) -> WeeklyReport:
    guidance_path = (HERE / cfg["ai"]["guidance_file"]).resolve()
    guidance = guidance_path.read_text(encoding="utf-8")

    # Watchlist lives next to guidance.md; appended so the provider caches both
    # as one block. Optional — pipeline still runs if the file isn't there.
    watchlist_rel = cfg["ai"].get("watchlist_file", "../ai/watchlist.md")
    watchlist_path = (HERE / watchlist_rel).resolve()
    if watchlist_path.exists():
        guidance = guidance + "\n\n---\n\n" + watchlist_path.read_text(encoding="utf-8")

    provider_name = env("AI_PROVIDER") or cfg["ai"].get("provider", "claude")
    provider = get_provider(provider_name)
    return provider.analyze(guidance=guidance, flyers=flyers, week_of=week_of)
