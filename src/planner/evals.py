"""Scoring the reconciled result against a case's expected values.

Exact fields (advertiser, budget, timeframe, restricted publishers) are scored
with exact match. Free-text fields cannot be exact-matched, so they get a
coarse presence check and are meant for an LLM judge or human review later
(the live script prints their values so you can read them).

A field listed in expected["conflicts"] must come out with exactly the status
named there ("conflict" or "ambiguous"); the overall "needs_input" check
compares the full set of fields that need the user.
"""

from __future__ import annotations

from typing import Any

from planner.summarize import Reconciled, _key, needs_input

EXACT = ("advertiser", "budget_usd", "timeframe", "restricted_publishers")
COARSE = (
    "goal_metric",
    "target_audience",
    "audience_provider_restriction",
    "existing_commitments",
    "buying_preferences",
)


def expected_needs_input(expected: dict[str, Any]) -> dict[str, str]:
    return {c["field"]: c.get("kind", "conflict") for c in expected.get("conflicts", [])}


def score(reconciled: Reconciled, expected: dict[str, Any]) -> dict[str, bool]:
    results: dict[str, bool] = {}
    wanted = expected_needs_input(expected)

    for field in EXACT + COARSE:
        r = reconciled[field]
        want = expected[field]
        if field in wanted:
            results[field] = r.status == wanted[field]
        elif field in EXACT:
            if field == "restricted_publishers":
                results[field] = _key(r.value or []) == _key(want)
            else:
                results[field] = r.status == "settled" and _key(r.value) == _key(want)
        else:  # coarse presence check
            has_actual = r.status not in ("missing", "conflict", "ambiguous") and bool(r.value)
            results[field] = bool(want) == has_actual

    results["needs_input"] = needs_input(reconciled) == wanted
    return results
