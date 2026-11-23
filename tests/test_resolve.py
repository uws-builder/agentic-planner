"""The confirmation step: options for fields that need the user, and resolving them."""

from __future__ import annotations

from planner.demo import demo_response
from planner.resolve import options_for, resolve
from planner.schema import Candidate, parse_extraction
from planner.summarize import reconcile


def conflict_case():
    return reconcile(parse_extraction(demo_response("summit_ridge_budget_conflict")))


def test_options_have_one_entry_per_distinct_value_with_sources():
    budget = options_for(conflict_case()["budget_usd"])
    assert [o.value for o in budget] == [800000, 1000000]
    assert budget[0].sources == ("chat",) and budget[1].sources == ("pdf",)
    assert "$800,000" in budget[0].label and "(chat)" in budget[0].label


def test_ambiguous_options_come_from_one_source():
    goal = options_for(conflict_case()["goal_metric"])
    assert len(goal) == 2
    assert all(o.sources == ("pdf",) for o in goal)


def test_same_value_from_two_sources_is_one_option():
    reconciled = reconcile(
        {
            "goal_metric": [
                Candidate("chat", "reach", "q"),
                Candidate("pdf", "Reach", "q"),
                Candidate("pdf", "purchases", "q"),
            ]
        }
    )
    options = options_for(reconciled["goal_metric"])
    assert len(options) == 2
    assert options[0].sources == ("chat", "pdf")


def test_not_ready_until_every_needs_input_field_has_a_choice():
    resolved = resolve(conflict_case(), {})
    assert resolved.pending == ("budget_usd", "goal_metric")
    assert not resolved.ready
    partial = resolve(conflict_case(), {"budget_usd": 1})
    assert partial.pending == ("goal_metric",)


def test_choices_become_the_resolved_values():
    resolved = resolve(conflict_case(), {"budget_usd": 0, "goal_metric": 1})
    assert resolved.ready
    assert resolved.values["budget_usd"] == 800000
    assert resolved.values["goal_metric"] == "qualified site traffic and purchases"
    assert resolved.how["budget_usd"] == "chosen by you (chat)"
    assert resolved.values["advertiser"] == "Summit Ridge Outdoors"
    assert resolved.how["advertiser"] == "from advertiser_record, chat, pdf"


def test_missing_fields_resolve_to_empty_not_pending():
    resolved = resolve(conflict_case(), {"budget_usd": 0, "goal_metric": 0})
    assert resolved.values["existing_commitments"] == []
    assert resolved.how["existing_commitments"] == "not stated"


def test_out_of_range_choice_is_treated_as_no_choice():
    resolved = resolve(conflict_case(), {"budget_usd": 7, "goal_metric": -1})
    assert resolved.pending == ("budget_usd", "goal_metric")


def test_to_dict_carries_schema_version():
    out = resolve(conflict_case(), {"budget_usd": 0, "goal_metric": 0}).to_dict()
    assert set(out) == {"schema_version", "values", "how"}
