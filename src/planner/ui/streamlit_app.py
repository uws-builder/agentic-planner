"""Basic demo UI: a chat-style flow for building a media plan.

Run:  .venv/bin/streamlit run src/planner/ui/streamlit_app.py

Flow: the agent greets you; you add your message and brief and click
"Build media plan"; the agent thinks; then it shows what it understood, with
choices where it needs you, and a "Create media plan" button.

A thin layer over the planner package; no logic lives here that isn't in a
tested module. Demo mode replays a saved extraction (free, repeatable). Real
mode calls the model with the key from .env. Backend steps are hidden unless
"Show debug details" is on in the sidebar.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import streamlit as st

from planner.cases import Case, discover_case_dirs, load_case
from planner.config import load_env
from planner.context import build_context
from planner.demo import DEMO_CASES, demo_response
from planner.model import AnthropicClient, ModelCallError, ScriptedClient
from planner.resolve import options_for, resolve
from planner.schema import FIELDS, SCHEMA_VERSION
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


@st.cache_resource
def load_cases() -> dict[str, Case]:
    return {d.name: load_case(d) for d in discover_case_dirs()}


CASES = load_cases()


# ---- state -----------------------------------------------------------------


def reset_run() -> None:
    for key in ("phase", "submitted", "run", "confirmed", "error"):
        st.session_state.pop(key, None)
    for key in [k for k in st.session_state if str(k).startswith("choice_")]:
        del st.session_state[key]


def on_example_change() -> None:
    name = st.session_state["case_name"]
    st.session_state["chat_text"] = CASES[name].bundle.chat_text if name in CASES else ""
    reset_run()


if "case_name" not in st.session_state:
    st.session_state["case_name"] = DEMO_CASES[0]
    st.session_state["chat_text"] = CASES[DEMO_CASES[0]].bundle.chat_text
st.session_state.setdefault("mode", DEMO)
st.session_state.setdefault("phase", "compose")


# ---- pipeline --------------------------------------------------------------


def run_pipeline(sub: dict[str, Any]) -> dict[str, Any]:
    timings: dict[str, float] = {}
    t = time.perf_counter()
    bundle = build_context(sub["chat_text"], pdf_path=sub["pdf_path"], advertiser=sub["advertiser"])
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
    mode = st.radio("Model", [DEMO, REAL], key="mode", on_change=reset_run)
    names = list(DEMO_CASES) if mode == DEMO else list(CASES) + [BLANK]
    if st.session_state["case_name"] not in names:
        st.session_state["case_name"] = names[0]
        st.session_state["chat_text"] = CASES[names[0]].bundle.chat_text
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
    st.button("Start over", key="start_over", on_click=reset_run)
    st.divider()
    st.caption(f"Extraction schema v{SCHEMA_VERSION}")

case = CASES.get(st.session_state["case_name"])
advertiser = case.bundle.advertiser if case else DEFAULT_ADVERTISER
phase = st.session_state["phase"]

st.title("📺 Agentic Media Planner")


# ---- chat pieces -----------------------------------------------------------


def user_bubble(sub: dict[str, Any]) -> None:
    with st.chat_message("user"):
        st.markdown(sub["chat_text"])
        if sub["pdf_name"]:
            st.caption(f"📎 {sub['pdf_name']}")


def render_cards(reconciled) -> dict[str, int | None]:
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
                picked = body.radio("Which should I use?", labels, index=None,
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


# ---- phase 1: compose ------------------------------------------------------

if phase == "compose":
    with st.chat_message("assistant"):
        st.markdown(
            "Hi! Add your message and your RFP or brief, and I'll read them and "
            "put together a media plan with you."
        )
        if st.session_state.get("error"):
            st.error(st.session_state["error"])

    with st.container(border=True):
        chat_text = st.text_area(
            "Your message",
            key="chat_text",
            height=110,
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
            elif case and case.bundle.pdf:
                pdf_path = case.bundle.pdf.source
                pdf_name = Path(pdf_path).name
                st.caption(f"No upload: using the example brief, 📎 {pdf_name}")
        if st.button("Build media plan", type="primary", key="build",
                     disabled=not chat_text.strip()):
            st.session_state["submitted"] = {
                "chat_text": chat_text,
                "pdf_path": pdf_path,
                "pdf_name": pdf_name,
                "advertiser": advertiser,
                "mode": mode,
                "case_name": st.session_state["case_name"],
            }
            st.session_state.pop("error", None)
            st.session_state["phase"] = "thinking"
            st.rerun()
    st.stop()

sub = st.session_state["submitted"]
user_bubble(sub)

# ---- phase 2: the agent thinks ---------------------------------------------

if phase == "thinking":
    failure = None
    with st.chat_message("assistant"):
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
        st.session_state["phase"] = "compose"
    else:
        st.session_state["run"] = run
        st.session_state["phase"] = "summary"
    st.rerun()

# ---- phase 3: summary and choices ------------------------------------------

run = st.session_state["run"]
reconciled = run["reconciled"]
n_need = sum(r.status in NEEDS_INPUT for r in reconciled.values())

with st.chat_message("assistant"):
    if n_need:
        noun = "item needs" if n_need == 1 else "items need"
        st.markdown(f"Here's what I understood. **{n_need} {noun} your call** before I build the plan.")
    else:
        st.markdown("Here's what I understood. Everything is clear, so I'm ready to build the plan.")
    choices = render_cards(reconciled)
    resolved = resolve(reconciled, choices)
    if st.button("Create media plan", type="primary", key="create_plan",
                 disabled=not resolved.ready):
        st.session_state["confirmed"] = json.dumps(resolved.to_dict(), sort_keys=True)
    if not resolved.ready:
        st.caption("Waiting on: " + ", ".join(LABELS[f] for f in resolved.pending))
    if st.session_state.get("debug"):
        st.divider()
        debug_panel(run)

# ---- phase 4: plan placeholder ---------------------------------------------

if st.session_state.get("confirmed") == json.dumps(resolved.to_dict(), sort_keys=True):
    with st.chat_message("assistant"):
        st.markdown("Great, I have everything I need. Here's what the plan step receives:")
        st.json(resolved.to_dict(), expanded=2)
        with st.container(border=True):
            st.markdown("**Draft plan: coming next (Job 2)**")
            st.markdown(
                "- Map the audience segments to audience IDs in the catalog\n"
                "- Discover eligible supply, with restricted publishers filtered out\n"
                "- Formulate and run the optimizer for the chosen goal\n"
                "- Validate every hard constraint before showing the plan\n"
                "- Explain the plan and take feedback"
            )
