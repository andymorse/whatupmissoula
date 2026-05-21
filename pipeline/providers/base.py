"""AI provider interface.

The pipeline only knows about this interface, so swapping Claude for a local
model later is a config change, not a rewrite. A provider takes the guidance
text plus the week's flyer images and returns a parsed WeeklyReport.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from schema import WeeklyReport


@dataclass
class FlyerImage:
    """One page of a flyer, ready for a vision model."""
    store_hint: str       # best guess of which store this flyer is from
    media_type: str       # e.g. "image/png", "image/jpeg"
    data_b64: str         # base64-encoded image bytes


class AIProvider(ABC):
    @abstractmethod
    def analyze(
        self,
        guidance: str,
        flyers: list[FlyerImage],
        week_of: str,
    ) -> WeeklyReport:
        """Extract structured deals from flyer images per the guidance doc."""
        raise NotImplementedError


def get_provider(name: str) -> AIProvider:
    """Factory: map a provider name to an implementation."""
    name = (name or "claude").lower()
    if name == "claude":
        from providers.claude import ClaudeProvider
        return ClaudeProvider()
    if name == "local":
        from providers.local import LocalProvider
        return LocalProvider()
    raise ValueError(f"Unknown AI provider: {name!r}")
