"""Advertiser commitments: existing deals the plan should honor.

A commitment is a budget floor, not a limit: the plan allocates at least the
remaining amount to that publisher, through that buying model, inside the plan's
timeframe. The plan is free to spend elsewhere too.

PG = Programmatic Guaranteed, DIO = Direct IO. The plan output labels both
"Guaranteed".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

DEAL_TYPES = ("PG", "DIO")


def timeframe_dates(timeframe: Any) -> tuple[date | None, date | None]:
    """Start and end dates from a resolved timeframe value, or (None, None)."""
    if not isinstance(timeframe, dict):
        return None, None
    try:
        return date.fromisoformat(timeframe["start"]), date.fromisoformat(timeframe["end"])
    except (KeyError, ValueError, TypeError):
        return None, None


def active_in(commitments: "list[Commitment] | tuple[Commitment, ...]",
              start: date | None, end: date | None) -> "list[Commitment]":
    """Commitments that overlap the plan's timeframe. If the timeframe is unknown,
    all of them are kept (the cautious choice: don't silently drop an obligation)."""
    if start is None or end is None:
        return list(commitments)
    return [c for c in commitments if c.start <= end and c.end >= start]


@dataclass(frozen=True)
class Commitment:
    id: str
    publisher: str
    deal_type: str
    remaining_usd: float
    start: date
    end: date
    note: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Commitment":
        if raw.get("deal_type") not in DEAL_TYPES:
            raise ValueError(f"commitment {raw.get('id')}: deal_type must be one of {DEAL_TYPES}")
        remaining = raw.get("remaining_usd")
        if not isinstance(remaining, (int, float)) or isinstance(remaining, bool) or remaining <= 0:
            raise ValueError(f"commitment {raw.get('id')}: remaining_usd must be a positive number")
        start, end = date.fromisoformat(raw["start"]), date.fromisoformat(raw["end"])
        if end < start:
            raise ValueError(f"commitment {raw.get('id')}: end is before start")
        return cls(
            id=raw["id"],
            publisher=raw["publisher"],
            deal_type=raw["deal_type"],
            remaining_usd=remaining,
            start=start,
            end=end,
            note=raw.get("note", ""),
        )
