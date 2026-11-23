"""Commitments and brand guidelines: types, fake services, and loading them into the bundle.

Principle under test: unknown or unavailable information is a warning, never a block."""

from __future__ import annotations

import json
import re
from datetime import date

import pytest

from planner.cases import discover_case_dirs, load_case
from planner.commitments import Commitment
from planner.context import (
    COMMITMENTS_UNAVAILABLE,
    GUIDELINES_UNAVAILABLE,
    NO_ADVERTISER_ID,
    NO_GUIDELINES,
    build_context,
)
from planner.guidelines import GuidelineSet, Rule
from planner.services import FIXTURES, FakeCommitments, FakeGuidelines, ServiceUnavailable

SUMMIT = {"advertiser_id": "adv_summit_ridge", "name": "Summit Ridge Outdoors"}
NO_GUIDELINES_ADV = {"advertiser_id": "adv_no_guidelines", "name": "Nobody Inc"}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


# ---- types -----------------------------------------------------------------


def commitment(**over):
    raw = {"id": "c", "publisher": "P", "deal_type": "PG", "remaining_usd": 10,
           "start": "2027-01-01", "end": "2027-02-01"}
    return {**raw, **over}


@pytest.mark.parametrize(
    "bad",
    [
        {"deal_type": "RTB"},
        {"remaining_usd": 0},
        {"remaining_usd": -5},
        {"remaining_usd": True},
        {"start": "2027-03-01", "end": "2027-02-01"},
        {"start": "not a date"},
    ],
)
def test_commitment_rejects_bad_data(bad):
    with pytest.raises(ValueError):
        Commitment.from_dict(commitment(**bad))


def test_commitment_parses_dates_and_deal_types():
    c = Commitment.from_dict(commitment(deal_type="DIO"))
    assert c.deal_type == "DIO" and c.start == date(2027, 1, 1) and c.end == date(2027, 2, 1)


def rule(**over):
    raw = {"id": "r", "type": "publisher_exclusion", "strength": "hard", "values": ["A"], "quote": "q"}
    return {**raw, **over}


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "viewability"},
        {"strength": "medium"},
        {"values": []},
        {"values": "A"},
        {"quote": "  "},
    ],
)
def test_rule_rejects_bad_data(bad):
    with pytest.raises(ValueError):
        Rule.from_dict(rule(**bad))


# ---- fixtures ---------------------------------------------------------------


def test_summit_ridge_commitments_fixture():
    commitments = FakeCommitments().get("adv_summit_ridge")
    assert [c.id for c in commitments] == ["cm_001", "cm_002", "cm_003"]
    assert {c.deal_type for c in commitments} == {"PG", "DIO"}
    # One commitment ends before the sample RFP's flight starts (2027-03-01).
    assert any(c.end < date(2027, 3, 1) for c in commitments)


def test_summit_ridge_guidelines_fixture_has_hard_and_soft_rules():
    g = FakeGuidelines().get("adv_summit_ridge")
    assert isinstance(g, GuidelineSet) and g.version == "2026.09"
    hard_pubs = g.rules_of("publisher_exclusion", "hard")
    soft_pubs = g.rules_of("publisher_exclusion", "soft")
    vendors = g.rules_of("audience_provider_allow", "hard")
    assert set(hard_pubs[0].values) == {"Vortex Stream", "Hollow Peak Media", "Dispatch Now News Network"}
    assert soft_pubs[0].values == ("Open Road Channels",)
    assert vendors[0].values == ("Meridian Audience Data",)


def test_every_compiled_rule_quote_is_in_the_guideline_text():
    g = FakeGuidelines().get("adv_summit_ridge")
    text = norm(g.raw_text)
    for r in g.rules:
        assert norm(r.quote) in text, f"{r.id}: quote not found in the document"


def test_every_fixture_rule_value_is_in_its_quote_or_the_document():
    g = FakeGuidelines().get("adv_summit_ridge")
    text = norm(g.raw_text)
    for r in g.rules:
        for value in r.values:
            assert norm(value) in text


def test_fixtures_are_marked_as_drafts_for_the_user_to_edit():
    raw = json.loads((FIXTURES / "adv_summit_ridge" / "guidelines.json").read_text())
    assert raw["draft"] is True


# ---- fake services ----------------------------------------------------------


def test_lookups_are_keyed_by_advertiser_id():
    assert FakeCommitments().get("adv_no_guidelines") == []
    assert FakeCommitments().get("adv_unknown") == []
    assert FakeGuidelines().get("adv_no_guidelines") is None
    assert FakeGuidelines().get("adv_unknown") is None


def test_one_advertisers_rules_never_come_back_for_another():
    for advertiser_id in ("adv_no_guidelines", "adv_unknown"):
        assert FakeGuidelines().get(advertiser_id) is None
        assert FakeCommitments().get(advertiser_id) == []


@pytest.mark.parametrize("fake", [FakeCommitments, FakeGuidelines])
def test_fault_injection_raises_service_unavailable(fake):
    with pytest.raises(ServiceUnavailable):
        fake(fail=True).get("adv_summit_ridge")


def test_corrupt_fixture_data_is_service_unavailable_not_a_crash(tmp_path):
    adv = tmp_path / "adv_x"
    adv.mkdir()
    (adv / "commitments.json").write_text(json.dumps([commitment(deal_type="RTB")]))
    (adv / "guidelines.json").write_text(json.dumps({"advertiser_id": "adv_x"}))  # missing keys
    with pytest.raises(ServiceUnavailable):
        FakeCommitments(root=tmp_path).get("adv_x")
    with pytest.raises(ServiceUnavailable):
        FakeGuidelines(root=tmp_path).get("adv_x")


# ---- the bundle -------------------------------------------------------------


def bundle(advertiser, **services):
    return build_context("hello", advertiser=advertiser, **services)


def test_bundle_carries_commitments_and_guidelines_with_no_warnings():
    b = bundle(SUMMIT, commitments_service=FakeCommitments(), guideline_store=FakeGuidelines())
    assert len(b.commitments) == 3
    assert b.guidelines is not None and len(b.guidelines.rules) == 3
    assert b.warnings == ()


def test_no_guidelines_on_file_is_a_warning_not_a_block():
    b = bundle(NO_GUIDELINES_ADV, commitments_service=FakeCommitments(), guideline_store=FakeGuidelines())
    assert b.guidelines is None
    assert b.commitments == ()  # none on file is normal and needs no warning
    assert b.warnings == (NO_GUIDELINES,)


def test_guideline_store_down_is_a_warning_not_a_block():
    b = bundle(SUMMIT, commitments_service=FakeCommitments(), guideline_store=FakeGuidelines(fail=True))
    assert b.guidelines is None
    assert b.warnings == (GUIDELINES_UNAVAILABLE,)
    assert len(b.commitments) == 3  # the other source still loaded


def test_commitments_down_is_a_warning_not_a_block():
    b = bundle(SUMMIT, commitments_service=FakeCommitments(fail=True), guideline_store=FakeGuidelines())
    assert b.commitments is None
    assert b.warnings == (COMMITMENTS_UNAVAILABLE,)
    assert b.guidelines is not None


def test_both_down_gives_both_warnings():
    b = bundle(SUMMIT, commitments_service=FakeCommitments(fail=True),
               guideline_store=FakeGuidelines(fail=True))
    assert set(b.warnings) == {COMMITMENTS_UNAVAILABLE, GUIDELINES_UNAVAILABLE}


@pytest.mark.parametrize("advertiser", [None, {}, {"name": "No id"}])
def test_missing_advertiser_id_is_a_warning(advertiser):
    b = bundle(advertiser, commitments_service=FakeCommitments(), guideline_store=FakeGuidelines())
    assert b.warnings == (NO_ADVERTISER_ID,)
    assert b.commitments is None and b.guidelines is None


def test_without_services_nothing_is_looked_up_and_nothing_warns():
    b = bundle(SUMMIT)
    assert b.commitments is None and b.guidelines is None and b.warnings == ()


def test_structured_sources_are_not_in_the_extraction_prompt_yet():
    b = bundle(SUMMIT, commitments_service=FakeCommitments(), guideline_store=FakeGuidelines())
    text = b.to_prompt_text()
    assert "Brand Buying Guidelines" not in text
    assert "Programmatic Guaranteed" not in text


# ---- cases ------------------------------------------------------------------


@pytest.mark.parametrize("case_dir", discover_case_dirs(), ids=lambda d: d.name)
def test_example_cases_load_their_advertisers_structured_context(case_dir):
    case = load_case(case_dir)
    assert len(case.bundle.commitments) == 3
    assert case.bundle.guidelines is not None
    assert case.bundle.warnings == ()
