"""Pipeline tests on a scripted model: schema parsing, quote checks, reconcile,
scoring, and rendering. These prove the wiring. They do NOT measure model
quality; that is what scripts/run_live_eval.py is for."""

from __future__ import annotations

import copy

import pytest

from planner.cases import Case, discover_case_dirs, load_case
from planner.demo import PUBLISHERS, demo_response as gold_response
from planner.evals import expected_needs_input, score
from planner.model import ScriptedClient
from planner.schema import Candidate, SchemaError, parse_extraction
from planner.summarize import (
    check_quotes,
    extract_intent,
    needs_input,
    reconcile,
    render_summary,
)

CASE_DIRS = discover_case_dirs()


@pytest.fixture(params=CASE_DIRS, ids=[d.name for d in CASE_DIRS])
def case(request) -> Case:
    return load_case(request.param)


def run(case: Case, response: dict):
    client = ScriptedClient([copy.deepcopy(response)])
    extraction = extract_intent(case.bundle, client)
    return client, extraction


def test_perfect_model_passes_every_check(case: Case):
    client, extraction = run(case, gold_response(case.name))
    assert check_quotes(extraction, case.bundle) == []
    results = score(reconcile(extraction), case.expected)
    assert all(results.values()), {k: v for k, v in results.items() if not v}
    assert len(client.calls) == 1
    assert "## Source: user chat message" in client.calls[0]["user"]
    assert client.calls[0]["output"] == "intent_extraction"


def test_needs_input_matches_expected_and_surfaces_in_summary(case: Case):
    _, extraction = run(case, gold_response(case.name))
    reconciled = reconcile(extraction)
    wanted = expected_needs_input(case.expected)
    assert needs_input(reconciled) == wanted
    summary = render_summary(reconciled)
    assert summary.count("NEEDS YOUR INPUT") == len(wanted)
    assert "Goal: NEEDS YOUR INPUT (several found, pick one)" in summary
    if "budget_usd" in wanted:
        assert "Budget: NEEDS YOUR INPUT (sources disagree)" in summary
        assert "$800,000" in summary and "$1,000,000" in summary
    else:
        assert "Budget: $1,000,000 (from chat, pdf)" in summary


def test_list_fields_merge_across_sources(case: Case):
    _, extraction = run(case, gold_response(case.name))
    reconciled = reconcile(extraction)
    assert reconciled["restricted_publishers"].value == PUBLISHERS
    audience = reconciled["target_audience"]
    assert audience.status == "settled" and len(audience.value) == 2


def _cand(source, value):
    return Candidate(source=source, value=value, quote="q")


def test_same_source_several_values_is_ambiguous_not_conflict():
    r = reconcile({"goal_metric": [_cand("pdf", "reach"), _cand("pdf", "purchases")]})
    assert r["goal_metric"].status == "ambiguous"


def test_different_sources_disagreeing_is_conflict():
    r = reconcile({"goal_metric": [_cand("chat", "reach"), _cand("pdf", "purchases")]})
    assert r["goal_metric"].status == "conflict"


def test_sources_agreeing_is_settled_even_with_different_wording_case():
    r = reconcile({"advertiser": [_cand("chat", "Acme  Corp"), _cand("pdf", "acme corp")]})
    assert r["advertiser"].status == "settled"


def test_list_fields_never_conflict():
    r = reconcile(
        {
            "restricted_publishers": [_cand("chat", ["A"]), _cand("pdf", ["B", "C"])],
            "target_audience": [_cand("chat", ["x"]), _cand("pdf", ["y"])],
        }
    )
    assert r["restricted_publishers"].value == ["A", "B", "C"]
    assert r["target_audience"].status == "settled"


def test_missing_field_is_reported_not_invented(case: Case):
    _, extraction = run(case, gold_response(case.name))
    r = reconcile(extraction)["existing_commitments"]
    assert r.status == "missing" and r.value == []
    assert "Existing commitments: not stated" in render_summary(reconcile(extraction))


def test_fabricated_quote_is_flagged(case: Case):
    response = gold_response(case.name)
    response["budget_usd"][0]["quote"] = "a budget of two million dollars"
    _, extraction = run(case, response)
    problems = check_quotes(extraction, case.bundle)
    assert [(p.field, p.source) for p in problems] == [("budget_usd", "chat")]


def test_wrong_budget_fails_the_score(case: Case):
    response = gold_response(case.name)
    response["budget_usd"] = [
        {"source": "pdf", "value": 900000, "quote": "$1,000,000"},
    ]
    _, extraction = run(case, response)
    results = score(reconcile(extraction), case.expected)
    assert results["budget_usd"] is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(surprise=[]),
        lambda r: r["budget_usd"][0].update(quote=""),
        lambda r: r["budget_usd"][0].update(value="a lot"),
        lambda r: r["budget_usd"][0].update(source="email"),
        lambda r: r["timeframe"][0].update(value={"start": "2027-03-01"}),
        lambda r: r["restricted_publishers"][0].update(value="Vortex Stream"),
    ],
)
def test_schema_rejects_malformed_output(mutate):
    response = gold_response("summit_ridge_clean")
    mutate(response)
    with pytest.raises(SchemaError):
        parse_extraction(response)
