"""AI enrichment for events: fill the gaps the feed can't.

The Roxy API has no MPAA rating or audience signal, so we ask Claude to flag
which films are genuinely kid/family-friendly and which are special events
(festivals, one-off classics, themed series), and to draft a short "weekend
pick" recommendation. Everything here is reviewed by a human before publish.

Tags are constrained to a small set so the page's badges/search stay tidy.
Degrades gracefully: no API key (or any error) → events keep their
deterministic feed tags and weekend_pick is left blank.
"""
from __future__ import annotations

import json
import os

from schema import Event

# AI may only add these (deterministic feed tags like "Annex" are kept as-is).
AI_TAGS = {"kid-friendly", "special-event"}

SYSTEM = (
    "You curate a Missoula community events page. You will get this weekend's "
    "films at The Roxy Theater (a nonprofit arthouse cinema). For each film, "
    "decide which of these tags apply: 'kid-friendly' (genuinely suitable and "
    "appealing for children/families — animation, all-ages programming, G/PG-"
    "level; when unsure, DON'T tag it), and 'special-event' (a festival, one-"
    "off classic, themed series, or anything beyond a standard new-release "
    "run — use the film's 'series' as a strong hint). Also write one warm, "
    "concise 'weekend pick' sentence recommending what to catch. Use your "
    "general film knowledge. Output ONLY JSON, no prose, no fences."
)


def _client_and_model():
    from anthropic import Anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, None
    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
    return Anthropic(api_key=api_key), model


def enrich_events(events: list[Event], week_of: str) -> str:
    """Add AI tags to ``events`` in place; return a weekend_pick string ("" if none)."""
    if not events:
        return ""
    client, model = _client_and_model()
    if client is None:
        return ""

    catalog = [
        {
            "title": e.title,
            "series": e.series or "",
            "runtime_min": e.runtime_min,
            "showtimes": [f"{s.day} {s.time}" for s in e.showtimes],
        }
        for e in events
    ]
    user = (
        f"Weekend of {week_of}. Films:\n{json.dumps(catalog, indent=2)}\n\n"
        'Return JSON: {"weekend_pick": "<one sentence>", '
        '"films": [{"title": "<exact title>", "tags": ["kid-friendly"|"special-event"]}]}'
    )

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=2000,
            system=SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        raw = "".join(b.text for b in resp.content if b.type == "text").strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1].removeprefix("json").strip()
        data = json.loads(raw)
    except Exception as e:  # AI is a nice-to-have; never sink the run
        print(f"  ! event enrichment skipped ({e})")
        return ""

    tags_by_title = {
        (f.get("title") or "").strip().lower():
            [t for t in f.get("tags", []) if t in AI_TAGS]
        for f in data.get("films", [])
    }
    for e in events:
        for t in tags_by_title.get(e.title.strip().lower(), []):
            if t not in e.tags:
                e.tags.append(t)

    return (data.get("weekend_pick") or "").strip()
