"""Checks on the context bundle and on the case files themselves.

These run over every folder in cases/, so a new case is covered automatically.
They also sanity-check the drafted ground truth: every expected value that
should be quoted from a source must actually appear in that source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from planner.cases import Case, discover_case_dirs, load_case
from planner.context import build_context

REQUIRED_EXPECTED_KEYS = {
    "advertiser",
    "budget_usd",
    "timeframe",
    "goal_metric",
    "target_audience",
    "restricted_publishers",
    "audience_provider_restriction",
    "existing_commitments",
    "buying_preferences",
    "conflicts",
}

CASE_DIRS = discover_case_dirs()


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def money(amount: int) -> str:
    return f"${amount:,}"


@pytest.fixture(params=CASE_DIRS, ids=[d.name for d in CASE_DIRS])
def case(request) -> Case:
    return load_case(request.param)


def test_cases_exist():
    assert CASE_DIRS, "no cases found under cases/"


def test_case_loads_with_all_sources(case: Case):
    assert case.bundle.chat_text.strip()
    assert case.bundle.pdf is not None and len(case.bundle.pdf.pages) > 0
    assert case.bundle.advertiser is not None


def test_expected_has_required_keys(case: Case):
    missing = REQUIRED_EXPECTED_KEYS - case.expected.keys()
    assert not missing, f"expected is missing keys: {sorted(missing)}"


def test_expected_values_are_grounded_in_sources(case: Case):
    """Drafted ground truth must be quotable from the inputs."""
    haystack = norm(case.bundle.to_prompt_text())
    assert norm(case.expected["advertiser"]) in haystack
    for publisher in case.expected["restricted_publishers"]:
        assert norm(publisher) in haystack
    budget = case.expected["budget_usd"]
    if budget is not None:
        assert money(budget) in haystack


def test_conflict_values_appear_in_their_sources(case: Case):
    chat = norm(case.bundle.chat_text)
    pdf = norm(case.bundle.pdf.text)
    sources = {"chat": chat, "pdf": pdf}
    for conflict in case.expected["conflicts"]:
        for source, value in conflict.get("values", {}).items():
            assert money(value) in sources[source], (
                f"{money(value)} not found in {source} for field {conflict['field']}"
            )


def test_prompt_text_labels_every_source(case: Case):
    text = case.bundle.to_prompt_text()
    assert "## Source: user chat message" in text
    assert "## Source: uploaded PDF" in text
    assert "## Source: advertiser record" in text


def test_build_context_with_chat_only():
    bundle = build_context("hello")
    assert bundle.pdf is None and bundle.advertiser is None
    assert bundle.to_prompt_text().startswith("## Source: user chat message")


def test_build_context_rejects_empty_chat():
    with pytest.raises(ValueError):
        build_context("   ")


def test_pdf_path_resolves_from_repo_root(tmp_path: Path):
    from planner.cases import REPO_ROOT, _resolve_pdf

    resolved = _resolve_pdf(tmp_path, "Streaming TV Media Plan RFP (Sample).pdf")
    assert resolved.parent == REPO_ROOT
