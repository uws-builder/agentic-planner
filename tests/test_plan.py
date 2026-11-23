"""The dummy plan: made-up numbers, but real arithmetic and real exclusion."""

from __future__ import annotations

import pytest

from planner.plan import (
    CATALOG,
    DEDUPE,
    PlanError,
    build_dummy_plan,
    plan_table_markdown,
    summary_rows,
)

RESTRICTED = ["Vortex Stream", "Hollow Peak Media", "Dispatch Now News Network"]


def values(budget=1_000_000, restricted=RESTRICTED, **extra):
    return {"budget_usd": budget, "restricted_publishers": restricted, **extra}


@pytest.mark.parametrize("budget", [1_000_000, 800_000, 333_333, 60_000, 9_999])
def test_line_budgets_add_up_exactly(budget):
    plan = build_dummy_plan(values(budget))
    assert sum(line.budget for line in plan.lines) == budget == plan.total_budget
    assert all(line.budget > 0 for line in plan.lines)


def test_restricted_publishers_are_excluded_whatever_the_casing():
    plan = build_dummy_plan(values(restricted=["vortex  STREAM", "Hollow Peak Media"]))
    names = {line.publisher for line in plan.lines}
    assert "Vortex Stream" not in names and "Hollow Peak Media" not in names
    assert set(plan.excluded) == {"Vortex Stream", "Hollow Peak Media"}


def test_with_the_sample_restrictions_exactly_the_other_publishers_remain():
    plan = build_dummy_plan(values())
    assert {line.publisher for line in plan.lines} == {
        e.name for e in CATALOG if e.name not in RESTRICTED
    }
    assert set(plan.excluded) == set(RESTRICTED)


def test_no_restrictions_means_every_publisher_is_used():
    plan = build_dummy_plan(values(restricted=[]))
    assert len(plan.lines) == len(CATALOG) and plan.excluded == ()


def test_lines_are_sorted_largest_budget_first():
    budgets = [line.budget for line in build_dummy_plan(values()).lines]
    assert budgets == sorted(budgets, reverse=True)


def test_reach_and_frequency_are_consistent():
    plan = build_dummy_plan(values())
    for line in plan.lines:
        assert line.reach == pytest.approx(line.impressions / line.frequency)
        assert 2 <= line.frequency <= 5
    summed = sum(line.reach for line in plan.lines)
    assert plan.total_reach == pytest.approx(summed * DEDUPE)
    assert max(line.reach for line in plan.lines) < plan.total_reach < summed
    assert plan.blended_frequency == pytest.approx(plan.total_impressions / plan.total_reach)


def test_deterministic():
    assert build_dummy_plan(values()) == build_dummy_plan(values())


@pytest.mark.parametrize("budget", [None, 0, -5, "a lot", True])
def test_needs_a_real_budget(budget):
    with pytest.raises(PlanError):
        build_dummy_plan(values(budget))


def test_errors_when_everything_is_excluded():
    with pytest.raises(PlanError):
        build_dummy_plan(values(restricted=[e.name for e in CATALOG]))


def test_table_has_a_total_row_and_omits_excluded_publishers():
    table = plan_table_markdown(build_dummy_plan(values()))
    assert "| **Total** |" in table and "**$1,000,000**" in table
    for name in RESTRICTED:
        assert name not in table
    assert table.count("\n") == len(build_dummy_plan(values()).lines) + 2  # header, rule, lines, total


def test_summary_rows_show_gathered_details_and_mark_gaps():
    rows = dict(
        summary_rows(
            {
                "advertiser": "Summit Ridge Outdoors",
                "budget_usd": 800000,
                "timeframe": {"start": "2027-03-01", "end": "2027-08-22"},
                "goal_metric": "reach and frequency",
                "restricted_publishers": RESTRICTED,
                "target_audience": [],
            }
        )
    )
    assert rows["Advertiser"] == "Summit Ridge Outdoors"
    assert rows["Budget"] == "$800,000"
    assert rows["Timeframe"] == "2027-03-01 to 2027-08-22"
    assert rows["Target audience"] == "not stated"
    assert "Vortex Stream" in rows["Restricted publishers"]
