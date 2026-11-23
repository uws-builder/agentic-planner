"""Dummy media plan, for illustration only.

Every number here is made up and deterministic. It is NOT built from real
inventory, pricing, forecasts or an optimizer; those pipes connect later (Job 2).
What it does use for real is the confirmed intent: the total budget is split
across a fictional publisher list so it always adds up exactly, and restricted
publishers are filtered out in code, never by a model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from planner.names import norm_name as _norm
from planner.rules import Constraints
from planner.summarize import LABELS, format_value

# Overlap between publishers: total unique reach is less than the sum of the lines.
DEDUPE = 0.82
FIELD_ORDER = (
    "advertiser",
    "budget_usd",
    "timeframe",
    "goal_metric",
    "target_audience",
    "restricted_publishers",
    "audience_provider_restriction",
    "buying_preferences",
)


class PlanError(ValueError):
    """The confirmed intent is not enough to draft a plan."""


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    kind: str
    weight: float  # relative share of budget
    cpm: float
    frequency: float  # average impressions per reached household


# Fictional. The three restricted names are the ones in the sample RFP, so the
# exclusion is visible in the demo.
CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry("Northlight Streaming", "Premium SVOD", 0.24, 30.0, 3.2),
    CatalogEntry("Vortex Stream", "Premium SVOD", 0.18, 29.0, 3.0),
    CatalogEntry("Summit Network Apps", "Network / vMVPD", 0.16, 26.0, 2.9),
    CatalogEntry("Hollow Peak Media", "Network / vMVPD", 0.12, 25.0, 2.8),
    CatalogEntry("TrailCast FAST", "FAST", 0.14, 18.0, 4.4),
    CatalogEntry("Open Road Channels", "FAST", 0.08, 16.0, 4.8),
    CatalogEntry("Arena Live", "Live sports", 0.12, 34.0, 2.6),
    CatalogEntry("Dispatch Now News Network", "Live news", 0.08, 27.0, 3.1),
    CatalogEntry("Shoppable CTV Exchange", "Performance CTV", 0.10, 24.0, 3.6),
)


@dataclass(frozen=True)
class PlanLine:
    publisher: str
    kind: str
    budget: int
    share: float
    impressions: float
    reach: float  # unique households
    frequency: float


@dataclass(frozen=True)
class Plan:
    lines: tuple[PlanLine, ...]
    total_budget: int
    total_impressions: float
    total_reach: float  # deduplicated
    blended_frequency: float
    excluded: tuple[str, ...]


def build_dummy_plan(
    values: dict[str, Any],
    catalog: tuple[CatalogEntry, ...] = CATALOG,
    constraints: Constraints | None = None,
) -> Plan:
    """With `constraints`, exactly the publishers it currently enforces are left out
    (hard rules, plus soft rules the user hasn't overridden). Without it, only the
    user's own restricted publishers are."""
    budget = values.get("budget_usd")
    if not isinstance(budget, (int, float)) or isinstance(budget, bool) or budget <= 0:
        raise PlanError("I still need a budget before I can draft a plan.")
    total = int(round(budget))

    if constraints is not None:
        restricted = constraints.enforced_names()
    else:
        restricted = {_norm(p) for p in values.get("restricted_publishers") or []}
    eligible = [e for e in catalog if _norm(e.name) not in restricted]
    excluded = tuple(e.name for e in catalog if _norm(e.name) in restricted)
    if not eligible:
        raise PlanError("Every publisher I know about is excluded by your restrictions.")

    weight_sum = sum(e.weight for e in eligible)
    step = 1000 if total >= 50_000 else 100
    budgets = [round(total * e.weight / weight_sum / step) * step for e in eligible]
    budgets[budgets.index(max(budgets))] += total - sum(budgets)  # make it add up exactly

    lines = []
    for entry, line_budget in sorted(zip(eligible, budgets), key=lambda p: -p[1]):
        impressions = line_budget / entry.cpm * 1000
        lines.append(
            PlanLine(
                publisher=entry.name,
                kind=entry.kind,
                budget=line_budget,
                share=line_budget / total,
                impressions=impressions,
                reach=impressions / entry.frequency,
                frequency=entry.frequency,
            )
        )

    total_impressions = sum(line.impressions for line in lines)
    total_reach = sum(line.reach for line in lines) * DEDUPE
    return Plan(
        lines=tuple(lines),
        total_budget=total,
        total_impressions=total_impressions,
        total_reach=total_reach,
        blended_frequency=total_impressions / total_reach,
        excluded=excluded,
    )


# ---- formatting ------------------------------------------------------------


def money(amount: float) -> str:
    return f"${amount:,.0f}"


def households(count: float) -> str:
    return f"{count / 1_000_000:.2f}M" if count >= 1_000_000 else f"{count / 1000:.0f}K"


def plan_table_markdown(plan: Plan) -> str:
    rows = ["| Publisher | Type | Budget | Share | Unique reach (HH) | Avg frequency |",
            "| --- | --- | ---: | ---: | ---: | ---: |"]
    for line in plan.lines:
        rows.append(
            f"| {line.publisher} | {line.kind} | {money(line.budget)} | {line.share:.0%} | "
            f"{households(line.reach)} | {line.frequency:.1f}x |"
        )
    rows.append(
        f"| **Total** | | **{money(plan.total_budget)}** | **100%** | "
        f"**{households(plan.total_reach)}** (deduplicated) | **{plan.blended_frequency:.1f}x** |"
    )
    return "\n".join(rows)


def summary_rows(values: dict[str, Any]) -> list[tuple[str, str]]:
    """Label and text for each gathered detail, for the summary above the plan."""
    rows = []
    for field in FIELD_ORDER:
        value = values.get(field)
        text = "not stated" if value in (None, [], "") else format_value(field, value)
        rows.append((LABELS[field], text))
    return rows
