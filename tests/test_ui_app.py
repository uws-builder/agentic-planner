"""Smoke tests for the Streamlit app using Streamlit's AppTest (no browser, demo mode,
no API calls). Real mode is only rendered, never run, so these never spend money."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "src" / "planner" / "ui" / "streamlit_app.py")


def fresh() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def understand(at: AppTest) -> AppTest:
    at.button(key="understand").click().run()
    assert not at.exception, at.exception
    return at


def test_loads_in_demo_mode_with_locked_inputs():
    at = fresh()
    assert at.radio(key="mode").value == "Demo (canned response)"
    assert at.text_area(key="chat_text").disabled
    assert "Summit Ridge Outdoors" in at.text_area(key="chat_text").value


def test_clean_case_needs_only_the_goal_then_confirms():
    at = understand(fresh())
    radio_keys = {r.key for r in at.radio if r.key and r.key.startswith("choice_")}
    assert radio_keys == {"choice_goal_metric"}
    assert at.button(key="confirm").disabled

    goal = at.radio(key="choice_goal_metric")
    goal.set_value(goal.options[0]).run()
    assert not at.button(key="confirm").disabled

    at.button(key="confirm").click().run()
    assert not at.exception
    assert any("Confirmed" in s.value for s in at.success)


def test_conflict_case_needs_budget_and_goal():
    at = fresh()
    at.selectbox(key="case_name").select("summit_ridge_budget_conflict").run()
    assert "$800,000" in at.text_area(key="chat_text").value
    understand(at)
    radio_keys = {r.key for r in at.radio if r.key and r.key.startswith("choice_")}
    assert radio_keys == {"choice_budget_usd", "choice_goal_metric"}

    budget = at.radio(key="choice_budget_usd")
    budget.set_value(budget.options[0]).run()
    assert at.button(key="confirm").disabled  # goal still unanswered
    goal = at.radio(key="choice_goal_metric")
    goal.set_value(goal.options[1]).run()
    assert not at.button(key="confirm").disabled


def test_changing_a_choice_after_confirming_hides_the_confirmation():
    at = understand(fresh())
    goal = at.radio(key="choice_goal_metric")
    goal.set_value(goal.options[0]).run()
    at.button(key="confirm").click().run()
    assert any("Confirmed" in s.value for s in at.success)
    goal = at.radio(key="choice_goal_metric")
    goal.set_value(goal.options[1]).run()
    assert not any("Confirmed" in s.value for s in at.success)


def test_real_mode_renders_with_a_blank_option_and_unlocked_inputs():
    at = fresh()
    at.radio(key="mode").set_value("Real model").run()
    assert not at.exception, at.exception
    assert "(blank: type your own)" in at.selectbox(key="case_name").options
    assert not at.text_area(key="chat_text").disabled
