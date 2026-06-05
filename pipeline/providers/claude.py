"""Claude (Anthropic API) provider.

Sends the guidance doc as a cached system prompt plus the week's flyer page
images, and parses the strict-JSON response into a WeeklyReport.

The guidance text is marked with cache_control so re-runs (and the large,
stable guidance block) are cheap. Requires ANTHROPIC_API_KEY in the env.
"""
from __future__ import annotations

import json
import os

from providers.base import AIProvider, FlyerImage
from schema import WeeklyReport


SYSTEM_PREAMBLE = (
    "You extract Missoula grocery flyer deals into strict JSON. Follow the "
    "guidance document below exactly. Output ONLY valid JSON per section 7 — "
    "no prose, no markdown fences."
)


class ClaudeProvider(AIProvider):
    def __init__(self, model: str | None = None):
        from anthropic import Anthropic  # imported lazily so the dep is optional

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self.client = Anthropic(api_key=api_key)
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
        # Output cap. The whole report is one JSON object, so too low a cap
        # truncates it mid-object and parsing fails. Many flyers (esp. Rosauers'
        # multi-page PDF) push the response large; default high and let .env
        # override. It's only a ceiling — you're billed for tokens generated.
        self.max_tokens = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "32000"))

    def analyze(self, guidance: str, flyers: list[FlyerImage], week_of: str) -> WeeklyReport:
        # System: short preamble + the (cached) guidance doc.
        system = [
            {"type": "text", "text": SYSTEM_PREAMBLE},
            {
                "type": "text",
                "text": "GUIDANCE DOCUMENT:\n\n" + guidance,
                "cache_control": {"type": "ephemeral"},
            },
        ]

        # User message: every flyer page as an image, labeled with its store hint.
        content: list[dict] = [{
            "type": "text",
            "text": (
                f"Week of {week_of}. Below are this week's store flyer pages. "
                "Extract deals and return the JSON object now."
            ),
        }]
        for fl in flyers:
            content.append({"type": "text", "text": f"--- Flyer (likely: {fl.store_hint}) ---"})
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": fl.media_type, "data": fl.data_b64},
            })

        # Stream: a high max_tokens can push the request past the SDK's 10-min
        # non-streaming ceiling, which raises before the call even goes out.
        # Streaming accumulates the chunks; get_final_message() returns the same
        # complete Message (content + stop_reason), and prompt caching still
        # applies to the system block.
        with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
        ) as stream:
            resp = stream.get_final_message()

        # A truncated response is invalid JSON; say so plainly instead of
        # surfacing a confusing "Expecting ',' delimiter" parse error.
        if resp.stop_reason == "max_tokens":
            raise ValueError(
                f"Claude hit the {self.max_tokens}-token output cap before "
                "finishing the JSON (response truncated). Raise "
                "ANTHROPIC_MAX_TOKENS in .env, or send fewer flyers per run."
            )

        raw = "".join(b.text for b in resp.content if b.type == "text").strip()
        data = _parse_json(raw)
        data.setdefault("week_of", week_of)
        return WeeklyReport.from_dict(data)


def _parse_json(raw: str) -> dict:
    """Tolerate an accidental ```json fence; otherwise expect clean JSON."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON: {e}\n---\n{raw[:500]}")
