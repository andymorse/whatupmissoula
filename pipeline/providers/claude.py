"""Claude (Anthropic API) provider.

Sends the guidance doc as a cached system prompt plus the week's flyer page
images, and parses the strict-JSON response into a WeeklyReport.

The guidance text is marked with cache_control so re-runs (and the large,
stable guidance block) are cheap. Requires ANTHROPIC_API_KEY in the env.
"""
from __future__ import annotations

import json
import os
import sys

from providers.base import AIProvider, FlyerImage
from schema import WeeklyReport


SYSTEM_PREAMBLE = (
    "You extract Missoula grocery flyer deals into strict JSON. Follow the "
    "guidance document below exactly. Output ONLY valid JSON per section 7 — "
    "no prose, no markdown fences. Do not include internal or system XML tags "
    "in your response."
)
# That last sentence guards against the model leaking internal XML into the
# visible response when thinking is off or light (seen on Claude Opus 5), which
# would break _parse_json. Keep it generic — naming the tags explicitly is measurably less
# effective, and an instruction telling the model not to think makes the leak
# *more* likely, not less.

# $ per million tokens (input, output, cache read) — only for the cost estimate
# printed after each run. Unknown models just skip the estimate.
_PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
}


class ClaudeProvider(AIProvider):
    def __init__(self, model: str | None = None):
        from anthropic import Anthropic  # imported lazily so the dep is optional

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self.client = Anthropic(api_key=api_key)
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        # Output cap. The whole report is one JSON object, so too low a cap
        # truncates it mid-object and parsing fails. It's only a ceiling —
        # you're billed for tokens generated, not for the headroom.
        #
        # Raised 32000 -> 64000 on 2026-08-19 (Albertsons made the report run
        # past 32K), then -> 128000 (the model's ceiling) on 2026-11-05 when
        # thinking was turned back on: max_tokens caps thinking + the JSON
        # *together*, so the reasoning needs room on top of the report.
        # Values this large REQUIRE the streaming call below — a non-streaming
        # request would hit the SDK's 10-minute timeout before it ever went out.
        self.max_tokens = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "128000"))
        # How hard the model thinks: low | medium | high | xhigh | max.
        self.effort = os.environ.get("ANTHROPIC_EFFORT", "medium")

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
        # Adaptive thinking at ANTHROPIC_EFFORT (default medium). Thinking was
        # off through Opus 5, but on Sonnet 5.5 thinking-off ("between_tools")
        # came back 27% thinner than Opus (43% fewer Rosauers deals, eggs and
        # butter missed) on 2026-11-05, so it's back on. Adaptive + effort works
        # on every current model, so this line no longer pins us to one model.
        with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            system=system,
            messages=[{"role": "user", "content": content}],
        ) as stream:
            resp = stream.get_final_message()
        _log_usage(self.model, self.effort, resp.usage)

        # A policy decline is HTTP 200 with no usable content; say so plainly.
        if resp.stop_reason == "refusal":
            raise ValueError(
                f"Claude declined the request (stop_details: {resp.stop_details})."
            )

        # A truncated response is invalid JSON; say so plainly instead of
        # surfacing a confusing "Expecting ',' delimiter" parse error.
        if resp.stop_reason == "max_tokens":
            raise ValueError(
                f"Claude hit the {self.max_tokens}-token output cap before "
                "finishing the JSON (response truncated). Raise "
                "ANTHROPIC_MAX_TOKENS in .env if it's set below 128000 (the "
                "model's ceiling; no rebuild needed, .env is a bind mount), "
                "lower ANTHROPIC_EFFORT, or send fewer flyers per run."
            )

        raw = "".join(b.text for b in resp.content if b.type == "text").strip()
        data = _parse_json(raw)
        data.setdefault("week_of", week_of)
        return WeeklyReport.from_dict(data)


def _log_usage(model: str, effort: str, usage) -> None:
    """One line per run: tokens + rough cost, so model/effort changes are measurable."""
    inp = usage.input_tokens or 0
    out = usage.output_tokens or 0
    cread = getattr(usage, "cache_read_input_tokens", 0) or 0
    cwrite = getattr(usage, "cache_creation_input_tokens", 0) or 0
    line = (f"  • AI usage ({model}, effort {effort}): {inp + cread + cwrite:,} in "
            f"({cread:,} cached), {out:,} out incl. thinking")
    price = _PRICES.get(model)
    if price:
        # Cache writes bill at 1.25x input for the default 5-minute TTL.
        cost = (inp * price[0] + cwrite * price[0] * 1.25
                + cread * price[2] + out * price[1]) / 1_000_000
        line += f" ≈ ${cost:.2f}"
    print(line, file=sys.stderr)


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
