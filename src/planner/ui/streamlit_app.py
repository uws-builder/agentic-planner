"""Basic demo UI: three sequential screens for building a media plan.

Run:  .venv/bin/streamlit run src/planner/ui/streamlit_app.py

  1. Input    your message and RFP/brief, then "Build media plan"
              (the agent visibly thinks, then moves you to screen 2)
  2. Verify   what the agent understood, with choices where it needs you,
              then "Create media plan"
  3. Plan     the summary of what we planned for, and the draft plan

Back buttons keep what you entered and chose. A thin layer over the planner
package; no logic lives here that isn't in a tested module. Demo mode replays
a saved extraction (free, repeatable). Real mode calls the model with the key
from .env. Backend details are hidden unless "Show debug details" is on.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from planner.cases import Case, discover_case_dirs, load_case
from planner.commitments import active_in, timeframe_dates
from planner.config import load_env
from planner.context import build_context
from planner.demo import DEMO_CASES, demo_response
from planner.model import AnthropicClient, ModelCallError, ScriptedClient
from planner.names import norm_name
from planner.plan import PlanError, build_dummy_plan, plan_table_markdown, summary_rows
from planner.resolve import options_for, resolve
from planner.rules import BLOCKER, INFO, WARNING, Constraints, compose_constraints, validate_plan
from planner.schema import FIELDS, SCHEMA_VERSION
from planner.services import FakeCommitments, FakeGuidelines
from planner.summarize import (
    LABELS,
    NEEDS_INPUT,
    check_quotes,
    extract_intent,
    format_value,
    reconcile,
)

load_env()
st.set_page_config(page_title="Agentic Media Planner", page_icon="📺", layout="centered")

DEMO, REAL = "Demo (canned response)", "Real model"
BLANK = "(blank: type your own)"
DEFAULT_ADVERTISER = {
    "advertiser_id": "adv_summit_ridge",
    "name": "Summit Ridge Outdoors",
    "category": "Outdoor retail",
}
# Demo mode replays instantly, so pause between "thinking" lines to make it visible.
# Set PLANNER_DEMO_DELAY=0 to skip (the tests do).
DEMO_DELAY = float(os.environ.get("PLANNER_DEMO_DELAY", "1.6"))
STEPS = ("Input", "Verify", "Plan")


@st.cache_resource
def load_cases() -> dict[str, Case]:
    return {d.name: load_case(d) for d in discover_case_dirs()}


CASES = load_cases()


# ---- state -----------------------------------------------------------------


def reset_all() -> None:
    """Back to a clean screen 1 with nothing remembered."""
    for key in ("phase", "submitted", "run", "run_sig", "saved_choices", "saved_overrides",
                "draft_chat", "pdf_choice", "error"):
        st.session_state.pop(key, None)
    for key in [k for k in st.session_state if str(k).startswith("choice_")]:
        del st.session_state[key]
    st.session_state.pop("chat_text", None)


def on_example_change() -> None:
    name = st.session_state["case_name"]
    reset_all()
    st.session_state["chat_text"] = CASES[name].bundle.chat_text if name in CASES else ""
    st.session_state["draft_chat"] = st.session_state["chat_text"]


def go(phase: str) -> None:
    st.session_state["phase"] = phase


if "case_name" not in st.session_state:
    st.session_state["case_name"] = DEMO_CASES[0]
st.session_state.setdefault("mode", DEMO)
st.session_state.setdefault("phase", "input")
st.session_state.setdefault("saved_choices", {})


def signature(sub: dict[str, Any]) -> tuple:
    return (sub["mode"], sub["case_name"], sub["chat_text"], sub["pdf_path"])


# ---- pipeline --------------------------------------------------------------


def run_pipeline(sub: dict[str, Any]) -> dict[str, Any]:
    timings: dict[str, float] = {}
    t = time.perf_counter()
    bundle = build_context(
        sub["chat_text"],
        pdf_path=sub["pdf_path"],
        advertiser=sub["advertiser"],
        commitments_service=FakeCommitments(),
        guideline_store=FakeGuidelines(),
    )
    timings["gather"] = time.perf_counter() - t

    client = (
        ScriptedClient([demo_response(sub["case_name"])])
        if sub["mode"] == DEMO
        else AnthropicClient()
    )
    t = time.perf_counter()
    extraction = extract_intent(bundle, client)
    timings["extract"] = time.perf_counter() - t

    t = time.perf_counter()
    problems = check_quotes(extraction, bundle)
    timings["verify"] = time.perf_counter() - t
    t = time.perf_counter()
    reconciled = reconcile(extraction)
    timings["reconcile"] = time.perf_counter() - t

    usage = getattr(client, "last_usage", None)
    return {
        "bundle": bundle,
        "extraction": extraction,
        "problems": problems,
        "reconciled": reconciled,
        "timings": timings,
        "tokens": f"{usage.input_tokens:,} in / {usage.output_tokens:,} out" if usage else None,
    }


# ---- sidebar ---------------------------------------------------------------

with st.sidebar:
    st.header("Setup")
    mode = st.radio("Model", [DEMO, REAL], key="mode", on_change=reset_all)
    names = list(DEMO_CASES) if mode == DEMO else list(CASES) + [BLANK]
    if st.session_state["case_name"] not in names:
        st.session_state["case_name"] = names[0]
    st.selectbox("Example case", names, key="case_name", on_change=on_example_change)
    if mode == DEMO:
        st.caption("Replays a saved extraction. Free and repeatable; inputs are locked.")
    else:
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        st.caption(
            "Calls the model with your key from `.env`."
            if has_key
            else "⚠️ No `ANTHROPIC_API_KEY` found. Add it to `.env`."
        )
    st.checkbox("Show debug details", key="debug")
    st.button("Start over", key="start_over", on_click=reset_all)
    st.divider()
    st.caption(f"Extraction schema v{SCHEMA_VERSION}")

case = CASES.get(st.session_state["case_name"])
advertiser = case.bundle.advertiser if case else DEFAULT_ADVERTISER
phase = st.session_state["phase"]

st.title("📺 Agentic Media Planner")


def step_indicator(current: int) -> None:
    parts = []
    for i, name in enumerate(STEPS, start=1):
        if i < current:
            parts.append(f"✓ {name}")
        elif i == current:
            parts.append(f"**● {i}. {name}**")
        else:
            parts.append(f"○ {i}. {name}")
    st.caption("  ›  ".join(parts))


# ---- shared pieces ---------------------------------------------------------


def render_cards(reconciled, saved: dict[str, int | None]) -> dict[str, int | None]:
    """One card per field, needing-input items first. Returns the user's choices."""
    choices: dict[str, int | None] = {}
    # sorted() is stable, so the normal field order is kept within each group.
    for field in sorted(FIELDS, key=lambda f: reconciled[f].status not in NEEDS_INPUT):
        result = reconciled[field]
        label = LABELS[field]
        with st.container(border=True):
            head, body = st.columns([1, 3])
            if result.status == "settled":
                head.markdown(f"✅ **{label}**")
                value = result.value
                body.markdown("\n\n".join(value) if isinstance(value, list)
                              else format_value(field, value))
                sources = ", ".join(sorted({c.source for c in result.candidates}))
                body.caption(f"from {sources}")
            elif result.status == "missing":
                head.markdown(f"➖ **{label}**")
                body.markdown("_not stated_")
            else:
                head.markdown(f"⚠️ **{label}**")
                why = ("The sources disagree." if result.status == "conflict"
                       else "I found several; the plan needs one.")
                body.markdown(f"**{why}**")
                options = options_for(result)
                labels = [o.label for o in options]
                picked = body.radio("Which should I use?", labels, index=saved.get(field),
                                    key=f"choice_{field}", label_visibility="collapsed")
                choices[field] = labels.index(picked) if picked in labels else None
            if result.candidates:
                with body.expander("Evidence"):
                    for c in result.candidates:
                        st.markdown(f"**{c.source}**: “{c.quote}”")
                        if c.note:
                            st.caption(f"note: {c.note}")
    return choices


def debug_panel(run: dict[str, Any]) -> None:
    timings = run["timings"]
    st.caption(
        "Debug · gather {g:.0f} ms (deterministic) · extract {e:.2f} s (model){t} · "
        "verify quotes {v:.0f} ms · reconcile {r:.0f} ms".format(
            g=timings["gather"] * 1000, e=timings["extract"],
            t=f" · {run['tokens']}" if run["tokens"] else "",
            v=timings["verify"] * 1000, r=timings["reconcile"] * 1000)
    )
    bundle = run["bundle"]
    guidelines = bundle.guidelines
    st.caption(
        "Looked up by advertiser ID: "
        + (f"{len(bundle.commitments)} commitment(s)" if bundle.commitments is not None
           else "commitments unavailable")
        + "; "
        + (f"guidelines '{guidelines.document_name}' v{guidelines.version} "
           f"({len(guidelines.rules)} rules)" if guidelines else "no guidelines")
        + ". Not yet part of what the model reads."
    )
    t1, t2, t3 = st.tabs(["What the model saw", "Raw extraction", "Quote check"])
    with t1:
        st.code(run["bundle"].to_prompt_text(), language="markdown")
    with t2:
        st.json({f: [c.__dict__ for c in cs] for f, cs in run["extraction"].items()},
                expanded=False)
    with t3:
        if run["problems"]:
            for p in run["problems"]:
                st.warning(f"{p.field} / {p.source}: {p.reason}: “{p.quote[:90]}”")
        else:
            st.success("Every quote was found in the source it cites.")


# ---- screens ---------------------------------------------------------------
# Each screen is rendered inside one placeholder (root), so a new screen replaces the
# old one immediately instead of leaving it faded underneath while the script runs.

root = st.empty()


def screen_input() -> None:
    step_indicator(1)
    st.subheader("Tell me what you need")
    st.markdown("Add your message and your RFP or brief, and I'll read them and put "
                "together a media plan with you.")
    if st.session_state.get("error"):
        st.error(st.session_state["error"])

    if "chat_text" not in st.session_state:  # widget state is dropped when you leave the screen
        st.session_state["chat_text"] = st.session_state.get(
            "draft_chat", case.bundle.chat_text if case else ""
        )
    with st.container(border=True):
        chat_text = st.text_area(
            "Your message",
            key="chat_text",
            height=120,
            disabled=(mode == DEMO),
            placeholder="e.g. I need a plan for Acme for Q1, $500,000 total. Don't run on Example News.",
        )
        pdf_path: str | None = None
        pdf_name: str | None = None
        if mode == DEMO:
            if case and case.bundle.pdf:
                pdf_path = case.bundle.pdf.source
                pdf_name = Path(pdf_path).name
                st.caption(f"📎 {pdf_name}")
        else:
            upload = st.file_uploader("RFP or brief (PDF), optional", type="pdf", key="pdf_upload")
            if upload is not None:
                tmp = Path(tempfile.mkdtemp()) / upload.name
                tmp.write_bytes(upload.getvalue())
                pdf_path, pdf_name = str(tmp), upload.name
                st.session_state["pdf_choice"] = (pdf_path, pdf_name)
            elif "pdf_choice" in st.session_state:
                pdf_path, pdf_name = st.session_state["pdf_choice"]
                st.caption(f"📎 Using {pdf_name} (uploaded earlier)")
            elif case and case.bundle.pdf:
                pdf_path = case.bundle.pdf.source
                pdf_name = Path(pdf_path).name
                st.caption(f"No upload: using the example brief, 📎 {pdf_name}")
        with st.expander("Advertiser from your session (stub)"):
            st.json(advertiser)

    if st.button("Build media plan", type="primary", key="build", disabled=not chat_text.strip()):
        sub = {
            "chat_text": chat_text,
            "pdf_path": pdf_path,
            "pdf_name": pdf_name,
            "advertiser": advertiser,
            "mode": mode,
            "case_name": st.session_state["case_name"],
        }
        st.session_state["draft_chat"] = chat_text
        st.session_state["submitted"] = sub
        st.session_state.pop("error", None)
        if "run" in st.session_state and st.session_state.get("run_sig") == signature(sub):
            st.session_state["phase"] = "verify"  # nothing changed: reuse, no second model call
        else:
            st.session_state.pop("run", None)
            st.session_state["saved_choices"] = {}
            st.session_state["phase"] = "thinking"
        st.rerun()


def screen_thinking() -> None:
    """The agent thinks: the transition from screen 1 to screen 2."""
    sub = st.session_state["submitted"]
    step_indicator(1)
    st.subheader("Reading your request")
    failure = None
    with st.status("Thinking…", expanded=True) as status:
        try:
            st.write("Reading your message…")
            time.sleep(DEMO_DELAY * 0.4 if sub["mode"] == DEMO else 0)
            st.write("Reading your brief…" if sub["pdf_name"] else "Checking the details…")
            time.sleep(DEMO_DELAY * 0.35 if sub["mode"] == DEMO else 0)
            st.write("Checking it all against each other…")
            run = run_pipeline(sub)
            time.sleep(DEMO_DELAY * 0.25 if sub["mode"] == DEMO else 0)
            status.update(label="Done thinking", state="complete", expanded=False)
        except ModelCallError as err:
            failure = f"I couldn't run the model: {err}"
        except Exception as err:  # keep the demo friendly: show the error, let them retry
            failure = f"Something went wrong ({type(err).__name__}): {err}"
        if failure:
            status.update(label="Something went wrong", state="error", expanded=False)
    if failure:
        st.session_state["error"] = failure
        st.session_state["phase"] = "input"
    else:
        st.session_state["run"] = run
        st.session_state["run_sig"] = signature(sub)
        st.session_state["phase"] = "verify"
    st.rerun()


def constraints_for(run: dict[str, Any], resolved, overrides: set[str]) -> Constraints:
    """The rules the plan must follow: brand guidelines plus what the user said."""
    bundle = run["bundle"]
    start, end = timeframe_dates(resolved.values.get("timeframe"))
    return compose_constraints(
        guidelines=bundle.guidelines,
        user_exclusions=resolved.values.get("restricted_publishers") or [],
        overrides=overrides,
        commitments=active_in(bundle.commitments or [], start, end),
    )


def render_notice(notice) -> None:
    {BLOCKER: st.error, WARNING: st.warning, INFO: st.info}[notice.level](notice.text)


def render_rules(run: dict[str, Any], resolved) -> Constraints:
    """The 'Brand rules' card. Hard rules are locked; soft ones can be included anyway
    (with a warning). Returns the constraints with the user's overrides applied."""
    saved: set[str] = set(st.session_state.get("saved_overrides", set()))
    base = constraints_for(run, resolved, set())
    if not (base.exclusions or base.allowed_providers):
        return base

    overrides: set[str] = set()
    st.markdown("**Brand rules and restrictions**")
    with st.container(border=True):
        hard = base.hard_exclusions()
        if hard:
            sources = sorted({s for e in hard for s in e.sources})
            st.markdown("🔒 **Won't run on:** " + ", ".join(e.publisher for e in hard))
            st.caption("From " + "; ".join(sources) + ". These can't be changed here.")
        if base.allowed_providers is not None:
            st.markdown("🔒 **Audience data:** only " + ", ".join(base.allowed_providers))
        for e in base.soft_exclusions():
            key = norm_name(e.publisher)
            if e.overridden:  # a commitment already pulled it in; the notice explains
                continue
            st.caption(f"{', '.join(e.sources).capitalize()} say to avoid {e.publisher}.")
            if st.checkbox(f"Include {e.publisher} anyway", value=key in saved,
                           key=f"override_{key}"):
                overrides.add(key)
        st.session_state["saved_overrides"] = overrides
        final = constraints_for(run, resolved, overrides)
        for notice in final.notices:
            render_notice(notice)
    return final


def screen_verify(run: dict[str, Any]) -> None:
    sub = st.session_state["submitted"]
    reconciled = run["reconciled"]
    step_indicator(2)
    st.subheader("Check what I understood")
    for warning in run["bundle"].warnings:
        st.warning(warning)
    n_need = sum(r.status in NEEDS_INPUT for r in reconciled.values())
    if n_need:
        noun = "item needs" if n_need == 1 else "items need"
        st.markdown(f"**{n_need} {noun} your call** before I can build the plan.")
    else:
        st.markdown("Everything is clear. Check it over, then create the plan.")
    with st.expander("Your request"):
        st.markdown(sub["chat_text"])
        if sub["pdf_name"]:
            st.caption(f"📎 {sub['pdf_name']}")

    choices = render_cards(reconciled, st.session_state["saved_choices"])
    st.session_state["saved_choices"] = choices
    resolved = resolve(reconciled, choices)
    constraints = render_rules(run, resolved)

    back_col, create_col, _ = st.columns([1, 2, 2])
    back_col.button("← Back", key="back_to_input", on_click=go, args=("input",))
    create_col.button("Create media plan", type="primary", key="create_plan",
                      disabled=not resolved.ready or bool(constraints.blockers),
                      on_click=go, args=("plan",))
    if not resolved.ready:
        st.caption("Waiting on: " + ", ".join(LABELS[f] for f in resolved.pending))
    if constraints.blockers:
        st.caption("I can't plan until the problem above is resolved.")
    if st.session_state.get("debug"):
        st.divider()
        debug_panel(run)


def screen_plan(run: dict[str, Any]) -> None:
    resolved = resolve(run["reconciled"], st.session_state["saved_choices"])
    if not resolved.ready:  # choices were lost; send the user back to answer them
        st.session_state["phase"] = "verify"
        st.rerun()

    constraints = constraints_for(run, resolved, set(st.session_state.get("saved_overrides", set())))
    if constraints.blockers:  # a known hard conflict: never plan against it
        st.session_state["phase"] = "verify"
        st.rerun()

    step_indicator(3)
    st.subheader("Your draft media plan")
    plan = None
    try:
        plan = build_dummy_plan(resolved.values, constraints=constraints)
        violations = validate_plan(plan, constraints)
    except PlanError as err:
        st.warning(str(err))
    else:
        if violations:  # the validator is the last line of defense; this should never show
            st.error("I can't show this plan because it breaks a rule I know about:")
            for v in violations:
                st.markdown(f"- {v.reason}")
            plan = None
    if plan is not None:
        for notice in constraints.warnings:
            st.warning(notice.text)
        st.markdown("**What I'm planning for**")
        with st.container(border=True):
            rows = summary_rows(resolved.values)
            left_col, right_col = st.columns(2)
            for i, (label, text) in enumerate(rows):
                (left_col if i < (len(rows) + 1) // 2 else right_col).markdown(
                    f"**{label}**  \n{text.replace('; ', ', ')}"
                )

        st.markdown("**Draft plan**")
        st.markdown(plan_table_markdown(plan))
        if plan.excluded:
            st.caption("Left out because of your restrictions and brand guidelines: "
                       + ", ".join(plan.excluded) + ".")
        st.caption(
            "Illustrative draft: every number here is made up. The real plan will come from "
            "your inventory, pricing and an optimizer."
        )
        with st.expander("What the plan step received"):
            st.json(resolved.to_dict(), expanded=2)

    back_col, restart_col, _ = st.columns([1, 1, 2])
    back_col.button("← Back", key="back_to_verify", on_click=go, args=("verify",))
    restart_col.button("Start over", key="plan_start_over", on_click=reset_all)


def scroll_to_top_on_screen_change() -> None:
    """Streamlit keeps the scroll position across reruns; a new screen should start at the top."""
    if st.session_state.get("_shown_phase") != phase:
        st.session_state["_shown_phase"] = phase
        components.html(
            f"""<script>/* {time.time()} */
            const doc = window.parent.document;
            const main = doc.querySelector('[data-testid="stMain"]') || doc.querySelector('section.main');
            if (main) main.scrollTo({{top: 0, behavior: 'instant'}});
            </script>""",
            height=0,
        )


with root.container():
    scroll_to_top_on_screen_change()
    if phase == "input":
        screen_input()
    elif phase == "thinking":
        screen_thinking()
    else:
        current_run = st.session_state.get("run")
        if current_run is None:  # e.g. the page was reloaded mid-flow
            st.session_state["phase"] = "input"
            st.rerun()
        elif phase == "verify":
            screen_verify(current_run)
        else:
            screen_plan(current_run)
