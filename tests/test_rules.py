"""Rule composition and the plan validator.

Constraints compose by restriction: exclusions union, audience-provider allow-lists
intersect, hard guideline rules can't be overridden, soft ones can with a warning.
Blocking is only for a known hard conflict."""

from __future__ import annotations

from datetime import date

import pytest

from planner.commitments import Commitment, active_in, timeframe_dates
from planner.names import norm_name
from planner.plan import build_dummy_plan
from planner.rules import (
    BLOCKER,
    INFO,
    WARNING,
    compose_constraints,
    validate_plan,
)
from planner.services import FakeCommitments, FakeGuidelines

HARD_PUBS = {"Vortex Stream", "Hollow Peak Media", "Dispatch Now News Network"}


@pytest.fixture(scope="module")
def guidelines():
    return FakeGuidelines().get("adv_summit_ridge")


def commitment(publisher, deal="PG", amount=100_000, start="2027-03-01", end="2027-06-30", id="cm_x"):
    return Commitment.from_dict(
        {"id": id, "publisher": publisher, "deal_type": deal, "remaining_usd": amount,
         "start": start, "end": end}
    )


def codes(constraints, level=None):
    return [n.code for n in constraints.notices if level is None or n.level == level]


# ---- publisher exclusions ---------------------------------------------------


def test_guidelines_alone_give_hard_and_soft_exclusions(guidelines):
    c = compose_constraints(guidelines=guidelines)
    assert {e.publisher for e in c.hard_exclusions()} == HARD_PUBS
    assert [e.publisher for e in c.soft_exclusions()] == ["Open Road Channels"]
    assert c.notices == () and c.blockers == []


def test_exclusions_are_a_union_with_the_users_own(guidelines):
    c = compose_constraints(guidelines=guidelines, user_exclusions=["Example News"])
    assert {e.publisher for e in c.hard_exclusions()} == HARD_PUBS | {"Example News"}


def test_same_publisher_from_two_sources_merges_whatever_the_casing(guidelines):
    c = compose_constraints(guidelines=guidelines, user_exclusions=["vortex   STREAM"])
    vortex = [e for e in c.exclusions if norm_name(e.publisher) == "vortex stream"]
    assert len(vortex) == 1
    assert vortex[0].publisher == "Vortex Stream"  # the guideline's spelling is kept
    assert "your request" in vortex[0].sources and any("guidelines" in s for s in vortex[0].sources)


def test_the_user_can_tighten_a_soft_rule_into_a_hard_one(guidelines):
    c = compose_constraints(guidelines=guidelines, user_exclusions=["Open Road Channels"])
    assert c.soft_exclusions() == []
    assert "Open Road Channels" in {e.publisher for e in c.hard_exclusions()}


def test_enforced_names_cover_hard_and_unoverridden_soft(guidelines):
    c = compose_constraints(guidelines=guidelines)
    assert c.enforced_names() == {norm_name(n) for n in HARD_PUBS | {"Open Road Channels"}}


def test_no_guidelines_and_no_user_input_means_no_constraints():
    c = compose_constraints(guidelines=None)
    assert c.exclusions == () and c.allowed_providers is None and c.notices == ()


# ---- requests and overrides -------------------------------------------------


def test_asking_for_a_hard_excluded_publisher_is_refused_with_an_explanation(guidelines):
    c = compose_constraints(guidelines=guidelines, requested_publishers=["vortex stream"])
    assert codes(c) == ["request_blocked_by_hard_rule"]
    assert c.notices[0].level == INFO and "§1.1" in c.notices[0].text
    assert norm_name("Vortex Stream") in c.enforced_names()
    assert c.blockers == []  # told, not blocked


def test_asking_for_a_soft_excluded_publisher_includes_it_with_a_warning(guidelines):
    c = compose_constraints(guidelines=guidelines, requested_publishers=["Open Road Channels"])
    assert codes(c, WARNING) == ["soft_rule_overridden"]
    assert "You asked for Open Road Channels" in c.notices[0].text
    assert norm_name("Open Road Channels") not in c.enforced_names()


def test_choosing_to_include_a_soft_publisher_warns(guidelines):
    c = compose_constraints(guidelines=guidelines, overrides=["Open Road Channels"])
    assert codes(c, WARNING) == ["soft_rule_overridden"]
    assert "You chose to include Open Road Channels" in c.notices[0].text
    assert [e.overridden for e in c.soft_exclusions()] == [True]


def test_a_hard_rule_cannot_be_overridden(guidelines):
    c = compose_constraints(guidelines=guidelines, overrides=["Vortex Stream", "Hollow Peak Media"])
    assert c.enforced_names() >= {norm_name(n) for n in HARD_PUBS}
    assert all(not e.overridden for e in c.hard_exclusions())


# ---- audience providers -----------------------------------------------------


def test_guideline_allow_list_applies_on_its_own(guidelines):
    c = compose_constraints(guidelines=guidelines)
    assert c.allowed_providers == ("Meridian Audience Data",)


def test_a_wider_user_list_is_narrowed_to_the_guideline_list(guidelines):
    c = compose_constraints(guidelines=guidelines,
                            user_allowed_providers=["Meridian Audience Data", "Other Co"])
    assert c.allowed_providers == ("Meridian Audience Data",)
    assert codes(c) == ["provider_narrowed"] and "Other Co" in c.notices[0].text


def test_disjoint_allow_lists_are_a_blocker(guidelines):
    c = compose_constraints(guidelines=guidelines, user_allowed_providers=["Other Co"])
    assert c.allowed_providers == ()
    assert codes(c, BLOCKER) == ["provider_allowlists_disjoint"]
    text = c.blockers[0].text
    assert "Meridian Audience Data" in text and "Other Co" in text


def test_the_users_allow_list_stands_when_there_are_no_guidelines():
    c = compose_constraints(guidelines=None, user_allowed_providers=["Meridian Audience Data"])
    assert c.allowed_providers == ("Meridian Audience Data",)
    assert c.notices == ()


def test_provider_names_match_whatever_the_casing(guidelines):
    c = compose_constraints(guidelines=guidelines, user_allowed_providers=["meridian audience  data"])
    assert c.allowed_providers == ("Meridian Audience Data",) and c.blockers == []


# ---- commitments vs exclusions ----------------------------------------------


def test_the_sample_commitments_conflict_with_nothing(guidelines):
    deals = FakeCommitments().get("adv_summit_ridge")
    c = compose_constraints(guidelines=guidelines, commitments=active_in(deals, date(2027, 3, 1), date(2027, 8, 22)))
    assert c.notices == ()


def test_a_commitment_with_a_hard_excluded_publisher_is_a_blocker(guidelines):
    c = compose_constraints(guidelines=guidelines, commitments=[commitment("Vortex Stream", "PG", 75_000)])
    assert codes(c, BLOCKER) == ["commitment_vs_hard_exclusion"]
    text = c.blockers[0].text
    assert "PG commitment" in text and "$75,000" in text and "Vortex Stream" in text
    assert "can't honor both" in text


def test_a_commitment_with_a_user_excluded_publisher_is_a_blocker_too():
    c = compose_constraints(guidelines=None, user_exclusions=["Acme TV"],
                            commitments=[commitment("acme tv", "DIO")])
    assert codes(c, BLOCKER) == ["commitment_vs_hard_exclusion"]
    assert "your request" in c.blockers[0].text


def test_a_commitment_with_a_soft_excluded_publisher_includes_it_with_a_warning(guidelines):
    c = compose_constraints(guidelines=guidelines, commitments=[commitment("Open Road Channels", "DIO")])
    assert codes(c, WARNING) == ["commitment_vs_soft_exclusion"]
    assert c.blockers == []
    assert norm_name("Open Road Channels") not in c.enforced_names()


def test_an_overridden_soft_publisher_with_a_commitment_warns_only_once(guidelines):
    c = compose_constraints(guidelines=guidelines, overrides=["Open Road Channels"],
                            commitments=[commitment("Open Road Channels")])
    assert codes(c) == ["soft_rule_overridden"]


# ---- commitments active in the timeframe ------------------------------------


def test_commitments_outside_the_timeframe_are_dropped():
    deals = FakeCommitments().get("adv_summit_ridge")
    ids = [c.id for c in active_in(deals, date(2027, 3, 1), date(2027, 8, 22))]
    assert ids == ["cm_001", "cm_002"]  # cm_003 ended 2027-02-15


def test_an_unknown_timeframe_keeps_every_commitment():
    deals = FakeCommitments().get("adv_summit_ridge")
    assert len(active_in(deals, None, None)) == 3


def test_overlap_is_inclusive_at_the_edges():
    c = commitment("P", start="2027-01-01", end="2027-03-01")
    assert active_in([c], date(2027, 3, 1), date(2027, 4, 1)) == [c]
    assert active_in([c], date(2027, 3, 2), date(2027, 4, 1)) == []


@pytest.mark.parametrize("value", [None, {}, {"start": "2027-01-01"}, {"start": "x", "end": "y"}, "soon"])
def test_timeframe_dates_tolerates_missing_or_bad_values(value):
    assert timeframe_dates(value) == (None, None)


def test_timeframe_dates_parses_a_resolved_value():
    assert timeframe_dates({"start": "2027-03-01", "end": "2027-08-22"}) == (date(2027, 3, 1), date(2027, 8, 22))


# ---- the plan and the validator ---------------------------------------------


def values(**over):
    return {"budget_usd": 1_000_000, "restricted_publishers": sorted(HARD_PUBS), **over}


def names(plan):
    return {line.publisher for line in plan.lines}


def test_plan_built_from_constraints_leaves_out_hard_and_soft_exclusions(guidelines):
    c = compose_constraints(guidelines=guidelines)
    plan = build_dummy_plan(values(), constraints=c)
    assert not names(plan) & (HARD_PUBS | {"Open Road Channels"})
    assert set(plan.excluded) == HARD_PUBS | {"Open Road Channels"}
    assert validate_plan(plan, c) == []


def test_overriding_a_soft_rule_puts_the_publisher_in_the_plan(guidelines):
    c = compose_constraints(guidelines=guidelines, overrides=["Open Road Channels"])
    plan = build_dummy_plan(values(), constraints=c)
    assert "Open Road Channels" in names(plan)
    assert validate_plan(plan, c) == []  # allowed: the user chose it
    assert sum(line.budget for line in plan.lines) == 1_000_000


def test_a_commitment_publisher_stays_in_the_plan_even_if_soft_excluded(guidelines):
    c = compose_constraints(guidelines=guidelines, commitments=[commitment("Open Road Channels")])
    assert "Open Road Channels" in names(build_dummy_plan(values(), constraints=c))


def test_the_validator_catches_a_plan_that_ignores_the_rules(guidelines):
    c = compose_constraints(guidelines=guidelines)
    sloppy = build_dummy_plan({"budget_usd": 1_000_000, "restricted_publishers": []})  # no constraints
    violations = validate_plan(sloppy, c)
    assert {v.publisher for v in violations} == HARD_PUBS | {"Open Road Channels"}
    reasons = {v.publisher: v.reason for v in violations}
    assert "excluded by brand guidelines §1.1" in reasons["Vortex Stream"]
    assert "set to be avoided by brand guidelines §1.2" in reasons["Open Road Channels"]


def test_the_validator_does_not_flag_an_overridden_soft_publisher(guidelines):
    c = compose_constraints(guidelines=guidelines, overrides=["Open Road Channels"])
    sloppy = build_dummy_plan({"budget_usd": 1_000_000, "restricted_publishers": []})
    assert {v.publisher for v in validate_plan(sloppy, c)} == HARD_PUBS


def test_without_constraints_the_plan_still_uses_the_users_restrictions():
    plan = build_dummy_plan(values())
    assert not names(plan) & HARD_PUBS and "Open Road Channels" in names(plan)


def test_composition_is_deterministic(guidelines):
    a = compose_constraints(guidelines=guidelines, requested_publishers=["Open Road Channels"])
    b = compose_constraints(guidelines=guidelines, requested_publishers=["Open Road Channels"])
    assert a == b
