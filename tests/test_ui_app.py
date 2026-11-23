"""Smoke tests for the Streamlit app using Streamlit's AppTest (no browser, demo mode,
no API calls). Real mode is only rendered, never run, so these never spend money."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "src" / "planner" / "ui" / "streamlit_app.py")


@pytest.fixture(autouse=True)
def no_demo_delay(monkeypatch):
    monkeypatch.setenv("PLANNER_DEMO_DELAY", "0")


def fresh() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def build(at: AppTest) -> AppTest:
    at.button(key="build").click().run()
    assert not at.exception, at.exception
    return at


def page_text(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    parts += [e.value for e in at.error] + [s.value for s in at.success]
    return "\n".join(parts)


def choice_keys(at: AppTest) -> set[str]:
    return {r.key for r in at.radio if r.key and r.key.startswith("choice_")}


def test_starts_as_a_chat_with_a_greeting_and_a_build_button():
    at = fresh()
    assert at.button(key="build").label == "Build media plan"
    assert "Add your message" in page_text(at)
    assert at.text_area(key="chat_text").disabled  # demo mode locks the inputs
    assert "Summit Ridge Outdoors" in at.text_area(key="chat_text").value


def test_building_shows_the_summary_and_hides_backend_steps():
    at = build(fresh())
    text = page_text(at)
    assert "Here's what I understood" in text
    assert "Summit Ridge Outdoors" in text
    for backend_step in ("Gather context", "Verify quotes", "Reconcile", "Deterministic"):
        assert backend_step not in text
    assert not any(b.key == "build" for b in at.button)  # the composer is replaced by the chat


def test_clean_case_needs_only_the_goal_then_creates_the_plan():
    at = build(fresh())
    assert choice_keys(at) == {"choice_goal_metric"}
    assert at.button(key="create_plan").disabled
    assert "draft media plan" not in page_text(at)

    goal = at.radio(key="choice_goal_metric")
    goal.set_value(goal.options[0]).run()
    assert not at.button(key="create_plan").disabled

    at.button(key="create_plan").click().run()
    assert not at.exception
    text = page_text(at)
    assert "Here's a draft media plan" in text
    assert "What I'm planning for" in text
    assert "| **Total** |" in text and "**$1,000,000**" in text
    assert "Left out because of your restrictions" in text
    assert "every number here is made up" in text


def test_restricted_publishers_never_appear_as_plan_lines():
    at = build(fresh())
    goal = at.radio(key="choice_goal_metric")
    goal.set_value(goal.options[0]).run()
    at.button(key="create_plan").click().run()
    table_rows = [m.value for m in at.markdown if "| Publisher |" in m.value]
    assert len(table_rows) == 1
    for name in ("Vortex Stream", "Hollow Peak Media", "Dispatch Now News Network"):
        assert f"| {name} |" not in table_rows[0]
    assert "| Northlight Streaming |" in table_rows[0]


def test_plan_total_follows_the_budget_the_user_picked():
    at = fresh()
    at.selectbox(key="case_name").select("summit_ridge_budget_conflict").run()
    build(at)
    budget = at.radio(key="choice_budget_usd")
    budget.set_value(budget.options[0]).run()  # the chat's $800,000
    goal = at.radio(key="choice_goal_metric")
    goal.set_value(goal.options[0]).run()
    at.button(key="create_plan").click().run()
    assert not at.exception
    assert "**$800,000**" in page_text(at)


def test_conflict_case_needs_budget_and_goal():
    at = fresh()
    at.selectbox(key="case_name").select("summit_ridge_budget_conflict").run()
    assert "$800,000" in at.text_area(key="chat_text").value
    build(at)
    assert choice_keys(at) == {"choice_budget_usd", "choice_goal_metric"}

    budget = at.radio(key="choice_budget_usd")
    budget.set_value(budget.options[0]).run()
    assert at.button(key="create_plan").disabled  # goal still unanswered
    goal = at.radio(key="choice_goal_metric")
    goal.set_value(goal.options[1]).run()
    assert not at.button(key="create_plan").disabled


def test_changing_a_choice_after_creating_hides_the_plan_step():
    at = build(fresh())
    goal = at.radio(key="choice_goal_metric")
    goal.set_value(goal.options[0]).run()
    at.button(key="create_plan").click().run()
    assert "Here's a draft media plan" in page_text(at)
    goal = at.radio(key="choice_goal_metric")
    goal.set_value(goal.options[1]).run()
    assert "Here's a draft media plan" not in page_text(at)


def test_debug_toggle_reveals_backend_details():
    at = build(fresh())
    assert "Debug" not in page_text(at)
    at.checkbox(key="debug").check().run()
    assert not at.exception
    assert "Debug" in page_text(at)


def test_start_over_returns_to_the_greeting():
    at = build(fresh())
    at.button(key="start_over").click().run()
    assert not at.exception
    assert at.button(key="build").label == "Build media plan"
    assert "Here's what I understood" not in page_text(at)


def test_real_mode_renders_with_a_blank_option_and_unlocked_inputs():
    at = fresh()
    at.radio(key="mode").set_value("Real model").run()
    assert not at.exception, at.exception
    assert "(blank: type your own)" in at.selectbox(key="case_name").options
    assert not at.text_area(key="chat_text").disabled
