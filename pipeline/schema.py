"""Data models for a weekly deals report.

These mirror the JSON contract in ai/guidance.md §7. The AI returns JSON; we
parse it into these dataclasses so the rest of the pipeline (render, publish)
works with typed objects instead of loose dicts.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict, fields
from typing import Optional


def _known(cls, d: dict) -> dict:
    """Keep only keys that are real fields of dataclass ``cls``.

    The model occasionally emits extra keys (e.g. an internal scratch field
    like ``note_internal``). Dropping unknowns here keeps one stray key from
    crashing the whole weekly run."""
    allowed = {f.name for f in fields(cls)}
    return {k: v for k, v in d.items() if k in allowed}


CATEGORIES = {
    "produce", "meat_seafood", "dairy_eggs", "bakery", "pantry",
    "frozen", "beverages", "snacks", "household", "other",
}
CONFIDENCE = {"high", "medium", "low"}


@dataclass
class Deal:
    item: str
    category: str = "other"
    sale_price: Optional[float] = None
    regular_price: Optional[float] = None
    unit: Optional[str] = None              # e.g. "$/lb", "$/oz", "$/dozen"
    unit_price: Optional[float] = None
    requires_loyalty: bool = False
    caveats: list[str] = field(default_factory=list)
    confidence: str = "high"
    note: Optional[str] = None
    watchlist_hit: bool = False
    watchlist_source: Optional[str] = None   # "mine" | "ai" when watchlist_hit

    @property
    def percent_off(self) -> Optional[int]:
        if self.sale_price and self.regular_price and self.regular_price > 0:
            return round((1 - self.sale_price / self.regular_price) * 100)
        return None


@dataclass
class StoreWeek:
    name: str
    in_scope: bool = True
    valid_from: Optional[str] = None        # ISO date
    valid_through: Optional[str] = None
    deals: list[Deal] = field(default_factory=list)
    # Optional store flavor — e.g. "bulk_wholesale" for CHEF'STORE so the site
    # can badge case-sized pricing distinctly from household grocery deals.
    kind: Optional[str] = None


@dataclass
class BestStore:
    name: str
    reason: str


@dataclass
class TopSteal:
    store: str
    item: str
    sale_price: Optional[float] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    caveats: list[str] = field(default_factory=list)
    watchlist_hit: bool = False
    watchlist_source: Optional[str] = None   # "mine" | "ai" when watchlist_hit


@dataclass
class WeeklyReport:
    week_of: str                            # ISO date (Monday)
    generated_note: str = ""
    best_store: Optional[BestStore] = None
    top_steals: list[TopSteal] = field(default_factory=list)
    stores: list[StoreWeek] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WeeklyReport":
        best = d.get("best_store")
        return cls(
            week_of=d["week_of"],
            generated_note=d.get("generated_note", ""),
            best_store=BestStore(**_known(BestStore, best)) if best else None,
            top_steals=[TopSteal(**_known(TopSteal, t)) for t in d.get("top_steals", [])],
            stores=[
                StoreWeek(
                    name=s["name"],
                    in_scope=s.get("in_scope", True),
                    valid_from=s.get("valid_from"),
                    valid_through=s.get("valid_through"),
                    deals=[Deal(**_known(Deal, deal)) for deal in s.get("deals", [])],
                    kind=s.get("kind"),
                )
                for s in d.get("stores", [])
            ],
        )
