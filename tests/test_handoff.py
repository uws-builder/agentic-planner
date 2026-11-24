"""Exporting a plan as a buyer handoff (plan_handoff.v0)."""

from __future__ import annotations

import json

import pytest

from planner.commitments import active_in, timeframe_dates
from planner.handoff import CPM_TOLERANCE_PCT, SCHEMA, HandoffError, build_handoff
from planner.plan import CATALOG, build_dummy_plan
from planner.rules import compose_constraints
from planner.services import FakeCommitments, FakeGuidelines

ADVERTISER = {"advertiser_id": "adv_summit_ridge", "name": "Summit Ridge Outdoors"}
RESTRICTED = ["Vortex Stream", "Hollow Peak Media", "Dispatch Now News Network"]
TIMEFRAME = {"start": "2027-03-01", "end": "2027-08-22"}


def export(values=None, overrides=(), advertiser=ADVERTISER, guidelines=True):
    values = values or {"budget_usd": 800_000, "timeframe": TIMEFRAME, "restricted_publishers": RESTRICTED}
    start, end = timeframe_dates(values.get("timeframe"))
    active = active_in(FakeCommitments().get("adv_summit_ridge"), start, end)
    constraints = compose_constraints(
        guidelines=FakeGuidelines().get("adv_summit_ridge") if guidelines else None,
        user_exclusions=values.get("restricted_publishers") or [],
        overrides=overrides,
        commitments=active,
    )
    plan = build_dummy_plan(values, constraints=constraints)
    return plan, build_handoff(plan, constraints, values, advertiser, active)


def test_shape_and_identity():
    _, h = export()
    assert h["schema"] == SCHEMA == "plan_handoff.v0"
    assert h["draft"] is True
    assert h["plan_id"] == "plan_adv_summit_ridge_20270301_20270822"
    assert (h["advertiser_id"], h["advertiser"]) == ("adv_summit_ridge", "Summit Ridge Outdoors")
    assert h["flight"] == TIMEFRAME
    json.dumps(h)  # plain JSON, nothing custom


def test_lines_match_the_plan_and_add_up():
    plan, h = export()
    assert [ln["line_id"] for ln in h["lines"]] == [f"L{i}" for i in range(1, len(plan.lines) + 1)]
    assert [ln["publisher"] for ln in h["lines"]] == [ln.publisher for ln in plan.lines]
    assert sum(ln["budget_usd"] for ln in h["lines"]) == h["total_budget_usd"] == 800_000
    cpms = {e.name: e.cpm for e in CATALOG}
    for ln in h["lines"]:
        assert ln["target_cpm"] == pytest.approx(cpms[ln["publisher"]])


def test_rules_are_carried_resolved():
    _, h = export()
    c = h["constraints"]
    assert set(c["excluded_publishers"]) == set(RESTRICTED)
    assert c["avoid_publishers"] == ["Open Road Channels"]  # soft, not overridden
    assert c["audience_providers"] == ["Meridian Audience Data"]
    assert c["cpm_tolerance_pct"] == CPM_TOLERANCE_PCT
    published = {ln["publisher"] for ln in h["lines"]}
    assert not published & set(c["excluded_publishers"] + c["avoid_publishers"])


def test_only_commitments_in_the_timeframe_are_handed_off():
    _, h = export()
    assert [(c["id"], c["deal_type"], c["min_spend_usd"]) for c in h["commitments"]] == [
        ("cm_001", "PG", 150_000), ("cm_002", "DIO", 80_000)]  # cm_003 ends before the plan


def test_an_overridden_soft_rule_is_not_on_the_avoid_list():
    _, h = export(overrides=["Open Road Channels"])
    assert h["constraints"]["avoid_publishers"] == []
    assert "Open Road Channels" in {ln["publisher"] for ln in h["lines"]}
    assert any("Open Road Channels" in n for n in h["planner_notes"])


def test_no_guidelines_means_no_provider_restriction():
    _, h = export(guidelines=False)
    assert h["constraints"]["audience_providers"] is None
    assert h["constraints"]["avoid_publishers"] == []


def test_refuses_without_dates():
    with pytest.raises(HandoffError, match="no start and end dates"):
        export(values={"budget_usd": 800_000, "restricted_publishers": RESTRICTED})


def test_refuses_without_an_advertiser():
    with pytest.raises(HandoffError, match="advertiser is unknown"):
        export(advertiser=None)


def test_refuses_with_a_blocker():
    values = {"budget_usd": 800_000, "timeframe": TIMEFRAME,
              "restricted_publishers": RESTRICTED + ["Northlight Streaming"]}  # has a PG commitment
    start, end = timeframe_dates(TIMEFRAME)
    active = active_in(FakeCommitments().get("adv_summit_ridge"), start, end)
    constraints = compose_constraints(guidelines=FakeGuidelines().get("adv_summit_ridge"),
                                      user_exclusions=values["restricted_publishers"], commitments=active)
    assert constraints.blockers
    plan = build_dummy_plan(values, constraints=constraints)
    with pytest.raises(HandoffError, match="unresolved blockers"):
        build_handoff(plan, constraints, values, ADVERTISER, active)
