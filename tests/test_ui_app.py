"""Smoke tests for the Streamlit app using Streamlit's AppTest (no browser, demo mode,
no API calls). Real mode is only rendered, never run, so these never spend money.

The app is three screens: 1 Input, 2 Verify, 3 Plan, with Back buttons."""

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


def click(at: AppTest, key: str) -> AppTest:
    at.button(key=key).click().run()
    assert not at.exception, at.exception
    return at


def build(at: AppTest) -> AppTest:
    return click(at, "build")


def page_text(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    parts += [e.value for e in at.error] + [s.value for s in at.success]
    parts += [w.value for w in at.warning] + [i.value for i in at.info]
    parts += [s.value for s in at.subheader]
    return "\n".join(parts)


def button_keys(at: AppTest) -> set[str]:
    return {b.key for b in at.button if b.key}


def choice_keys(at: AppTest) -> set[str]:
    return {r.key for r in at.radio if r.key and r.key.startswith("choice_")}


def choose(at: AppTest, field: str, index: int) -> AppTest:
    radio = at.radio(key=f"choice_{field}")
    radio.set_value(radio.options[index]).run()
    assert not at.exception, at.exception
    return at


def to_plan(at: AppTest, budget_index: int | None = None) -> AppTest:
    """From screen 2, answer every open question (goal: first option) and create the plan."""
    if budget_index is not None:
        choose(at, "budget_usd", budget_index)
    choose(at, "goal_metric", 0)
    return click(at, "create_plan")


# ---- screen 1 --------------------------------------------------------------


def test_screen_1_is_the_input_page():
    at = fresh()
    text = page_text(at)
    assert "Tell me what you need" in text
    assert "1. Input" in text
    assert at.button(key="build").label == "Build media plan"
    assert at.text_area(key="chat_text").disabled  # demo mode locks the inputs
    assert "Summit Ridge Outdoors" in at.text_area(key="chat_text").value
    assert button_keys(at) == {"build", "start_over"}


# ---- screen 2 --------------------------------------------------------------


def test_building_moves_to_the_verify_screen_and_hides_backend_steps():
    at = build(fresh())
    text = page_text(at)
    assert "Check what I understood" in text
    assert "2. Verify" in text
    assert "Summit Ridge Outdoors" in text
    for backend_step in ("Gather context", "Verify quotes", "Reconcile", "Deterministic"):
        assert backend_step not in text
    assert "build" not in button_keys(at)  # screen 1 is gone
    assert {"back_to_input", "create_plan"} <= button_keys(at)


def test_clean_case_needs_only_the_goal():
    at = build(fresh())
    assert choice_keys(at) == {"choice_goal_metric"}
    assert at.button(key="create_plan").disabled
    choose(at, "goal_metric", 0)
    assert not at.button(key="create_plan").disabled


def test_conflict_case_needs_budget_and_goal():
    at = fresh()
    at.selectbox(key="case_name").select("summit_ridge_budget_conflict").run()
    assert "$800,000" in at.text_area(key="chat_text").value
    build(at)
    assert choice_keys(at) == {"choice_budget_usd", "choice_goal_metric"}
    choose(at, "budget_usd", 0)
    assert at.button(key="create_plan").disabled  # goal still unanswered
    choose(at, "goal_metric", 1)
    assert not at.button(key="create_plan").disabled


def test_debug_toggle_reveals_backend_details_on_screen_2():
    at = build(fresh())
    assert "Debug" not in page_text(at)
    at.checkbox(key="debug").check().run()
    assert not at.exception
    assert "Debug" in page_text(at)


# ---- screen 3 --------------------------------------------------------------


def test_create_plan_moves_to_the_plan_screen():
    at = to_plan(build(fresh()))
    text = page_text(at)
    assert "Your draft media plan" in text
    assert "3. Plan" in text
    assert "What I'm planning for" in text
    assert "| **Total** |" in text and "**$1,000,000**" in text
    assert "Left out because of your restrictions" in text
    assert "every number here is made up" in text
    assert choice_keys(at) == set()  # the verify cards are gone
    assert {"back_to_verify", "plan_start_over"} <= button_keys(at)


def test_restricted_publishers_never_appear_as_plan_lines():
    at = to_plan(build(fresh()))
    tables = [m.value for m in at.markdown if "| Publisher |" in m.value]
    assert len(tables) == 1
    for name in ("Vortex Stream", "Hollow Peak Media", "Dispatch Now News Network"):
        assert f"| {name} |" not in tables[0]
    assert "| Northlight Streaming |" in tables[0]


def test_plan_total_follows_the_budget_the_user_picked():
    at = fresh()
    at.selectbox(key="case_name").select("summit_ridge_budget_conflict").run()
    to_plan(build(at), budget_index=0)  # the chat's $800,000
    assert "**$800,000**" in page_text(at)


# ---- brand rules -----------------------------------------------------------

OPEN_ROAD = "override_open road channels"


def plan_tables(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown if "| Publisher |" in m.value]


def test_verify_screen_shows_the_brand_rules_with_hard_rules_locked():
    at = build(fresh())
    text = page_text(at)
    assert "Brand rules and restrictions" in text
    assert "Won't run on:" in text and "Vortex Stream" in text
    assert "Audience data:** only Meridian Audience Data" in text
    assert "brand guidelines §1.1" in text
    # only the soft rule can be toggled; the hard ones are not choices at all
    assert {c.key for c in at.checkbox if c.key and c.key.startswith("override_")} == {OPEN_ROAD}
    assert not at.checkbox(key=OPEN_ROAD).value


def test_soft_rule_publisher_is_left_out_by_default_and_the_caption_says_so():
    at = to_plan(build(fresh()))
    table = plan_tables(at)[0]
    assert "| Open Road Channels |" not in table
    assert "Left out because of your restrictions and brand guidelines" in page_text(at)
    assert "Open Road Channels" in page_text(at)


def test_including_a_soft_publisher_anyway_warns_and_puts_it_in_the_plan():
    at = build(fresh())
    at.checkbox(key=OPEN_ROAD).check().run()
    assert not at.exception, at.exception
    assert "You chose to include Open Road Channels" in page_text(at)
    to_plan(at)
    assert "| Open Road Channels |" in plan_tables(at)[0]
    assert "You chose to include Open Road Channels" in page_text(at)  # the warning follows to screen 3
    for name in ("Vortex Stream", "Hollow Peak Media", "Dispatch Now News Network"):
        assert f"| {name} |" not in plan_tables(at)[0]  # hard rules still hold


def test_the_override_survives_going_back_and_can_be_undone():
    at = build(fresh())
    at.checkbox(key=OPEN_ROAD).check().run()
    to_plan(at)
    click(at, "back_to_verify")
    assert at.checkbox(key=OPEN_ROAD).value  # kept
    at.checkbox(key=OPEN_ROAD).uncheck().run()
    click(at, "create_plan")
    assert "| Open Road Channels |" not in plan_tables(at)[0]
    assert "You chose to include" not in page_text(at)


def test_start_over_forgets_the_override():
    at = build(fresh())
    at.checkbox(key=OPEN_ROAD).check().run()
    click(at, "start_over")
    build(at)
    assert not at.checkbox(key=OPEN_ROAD).value


# ---- back buttons ----------------------------------------------------------


def test_back_from_verify_returns_to_input_with_the_text_kept():
    at = build(fresh())
    click(at, "back_to_input")
    assert "Tell me what you need" in page_text(at)
    assert "Summit Ridge Outdoors" in at.text_area(key="chat_text").value


def test_going_back_and_forward_keeps_choices_and_skips_a_second_run():
    at = build(fresh())
    choose(at, "goal_metric", 1)
    picked = at.radio(key="choice_goal_metric").value
    click(at, "back_to_input")
    build(at)  # unchanged inputs: straight back to screen 2, no thinking again
    assert "Check what I understood" in page_text(at)
    assert at.radio(key="choice_goal_metric").value == picked
    assert not at.button(key="create_plan").disabled


def test_back_from_plan_keeps_choices_and_lets_you_change_them():
    at = fresh()
    at.selectbox(key="case_name").select("summit_ridge_budget_conflict").run()
    to_plan(build(at), budget_index=0)
    assert "**$800,000**" in page_text(at)

    click(at, "back_to_verify")
    assert "Check what I understood" in page_text(at)
    assert not at.button(key="create_plan").disabled  # earlier choices were kept
    choose(at, "budget_usd", 1)  # now the PDF's $1,000,000
    click(at, "create_plan")
    text = page_text(at)
    assert "**$1,000,000**" in text and "**$800,000**" not in text


def test_start_over_clears_everything_and_returns_to_screen_1():
    at = to_plan(build(fresh()))
    click(at, "plan_start_over")
    assert "Tell me what you need" in page_text(at)
    build(at)
    assert at.button(key="create_plan").disabled  # the earlier choice was forgotten


# ---- real mode (rendered only) ---------------------------------------------


def test_real_mode_renders_with_a_blank_option_and_unlocked_inputs():
    at = fresh()
    at.radio(key="mode").set_value("Real model").run()
    assert not at.exception, at.exception
    assert "(blank: type your own)" in at.selectbox(key="case_name").options
    assert not at.text_area(key="chat_text").disabled
