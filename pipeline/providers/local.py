"""Local LLM provider — placeholder for a future self-hosted model.

Kept as a stub so the provider interface stays honest. When we evaluate a local
vision model, implement analyze() here (same contract as ClaudeProvider) and set
AI_PROVIDER=local. Nothing else in the pipeline needs to change.
"""
from __future__ import annotations

from providers.base import AIProvider, FlyerImage
from schema import WeeklyReport


class LocalProvider(AIProvider):
    def analyze(self, guidance: str, flyers: list[FlyerImage], week_of: str) -> WeeklyReport:
        raise NotImplementedError(
            "Local provider not implemented yet. Use AI_PROVIDER=claude for now."
        )
