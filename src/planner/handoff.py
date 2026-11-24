"""Export a finished plan as a buyer handoff (`plan_handoff.v0`).

This is the only module that knows the buyer's format (see agentic-buyer
docs/handoff.md). The rest of the planner stays free to change shape; when it
does, only this adapter and its tests should need to follow.

The handoff carries every rule the buyer must obey, already resolved, so the
buyer never re-reads the RFP or guidelines. Export refuses anything the buyer
couldn't act on safely: an unresolved blocker, a missing flight, or a plan that
breaks a rule the planner knows about.
"""

from __future__ import annotations

from typing import Any, Iterable

from planner.commitments import Commitment, timeframe_dates
from planner.plan import Plan
from planner.rules import Constraints, validate_plan

SCHEMA = "plan_handoff.v0"

# How far above a line's planned CPM the buyer may book. The planner has no
# pricing yet, so this is a fixed placeholder until planning sets it per line.
CPM_TOLERANCE_PCT = 10


class HandoffError(ValueError):
    """The plan can't be handed to the buyer yet."""


def build_handoff(
    plan: Plan,
    constraints: Constraints,
    values: dict[str, Any],
    advertiser: dict[str, Any] | None,
    commitments: Iterable[Commitment] = (),
) -> dict[str, Any]:
    """`values` are the resolved intent values, `commitments` the ones active in the
    plan's timeframe (as passed to compose_constraints)."""
    problems = []
    if constraints.blockers:
        problems.append("there are unresolved blockers: " + "; ".join(n.text for n in constraints.blockers))
    if validate_plan(plan, constraints):
        problems.append("the plan breaks a rule the planner knows about")
    start, end = timeframe_dates(values.get("timeframe"))
    if start is None or end is None:
        problems.append("the plan has no start and end dates")
    advertiser_id = (advertiser or {}).get("advertiser_id")
    if not advertiser_id:
        problems.append("the advertiser is unknown, so commitments and guidelines weren't checked")
    if problems:
        raise HandoffError("Can't hand this plan to the buyer: " + "; ".join(problems) + ".")

    lines = []
    for i, line in enumerate(plan.lines, start=1):
        if line.impressions <= 0:
            raise HandoffError(f"{line.publisher} has no impressions, so its CPM is unknown.")
        lines.append({
            "line_id": f"L{i}",
            "publisher": line.publisher,
            "kind": line.kind,
            "budget_usd": int(line.budget),
            "target_cpm": round(line.budget / line.impressions * 1000, 2),
        })

    return {
        "schema": SCHEMA,
        "draft": True,  # the plan numbers are still the dummy generator's
        "plan_id": f"plan_{advertiser_id}_{start:%Y%m%d}_{end:%Y%m%d}",
        "advertiser_id": advertiser_id,
        "advertiser": (advertiser or {}).get("name") or values.get("advertiser") or advertiser_id,
        "flight": {"start": start.isoformat(), "end": end.isoformat()},
        "total_budget_usd": int(plan.total_budget),
        "lines": lines,
        "constraints": {
            "excluded_publishers": [e.publisher for e in constraints.hard_exclusions()],
            # Soft rules the user didn't override. Ones they overrode were a deliberate choice.
            "avoid_publishers": [e.publisher for e in constraints.soft_exclusions() if e.enforced],
            "audience_providers": (None if constraints.allowed_providers is None
                                   else list(constraints.allowed_providers)),
            "cpm_tolerance_pct": CPM_TOLERANCE_PCT,
        },
        "commitments": [
            {
                "id": c.id,
                "publisher": c.publisher,
                "deal_type": c.deal_type,
                "min_spend_usd": int(round(c.remaining_usd)),
                "start": c.start.isoformat(),
                "end": c.end.isoformat(),
            }
            for c in commitments
        ],
        # Informational; the buyer shows these to its approver but doesn't act on them.
        "planner_notes": [n.text for n in constraints.notices if n.level == "warning"],
    }
