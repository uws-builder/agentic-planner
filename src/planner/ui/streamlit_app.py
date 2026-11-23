"""Basic demo UI for Job 1: understand the request, then confirm.

Run:  .venv/bin/streamlit run src/planner/ui/streamlit_app.py

A thin layer over the planner package; no logic lives here that isn't in a
tested module. Demo mode replays a saved extraction (free, repeatable). Real
mode calls the model with the key from .env.
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
st.set_page_config(page_title="Agentic Media Planner", page_icon="📺", layout="wide")

DEMO, REAL = "Demo (canned response)", "Real model"
BLANK = "(blank: type your own)"
DEFAULT_ADVERTISER = {
    "advertiser_id": "adv_summit_ridge",
    "name": "Summit Ridge Outdoors",
    "category": "Outdoor retail",
}


@st.cache_resource
def load_cases() -> dict[str, Case]:
    return {d.name: load_case(d) for d in discover_case_dirs()}


CASES = load_cases()


# ---- state helpers ---------------------------------------------------------


def on_example_change() -> None:
    name = st.session_state["case_name"]
    st.session_state["chat_text"] = CASES[name].bundle.chat_text if name in CASES else ""
    reset_run()


def reset_run() -> None:
    for key in ("run", "confirmed"):
        st.session_state.pop(key, None)
    for key in [k for k in st.session_state if str(k).startswith("choice_")]:
        del st.session_state[key]


def init_state() -> None:
    st.session_state.setdefault("mode", DEMO)
    if "case_name" not in st.session_state:
        st.session_state["case_name"] = DEMO_CASES[0]
        st.session_state["chat_text"] = CASES[DEMO_CASES[0]].bundle.chat_text


init_state()


# ---- pipeline --------------------------------------------------------------


def run_pipeline(mode: str, case_name: str, chat_text: str, pdf_path: str | None,
                 advertiser: dict[str, Any]) -> dict[str, Any]:
    timings: dict[str, float] = {}
    t = time.perf_counter()
    bundle = build_context(chat_text, pdf_path=pdf_path, advertiser=advertiser)
    timings["gather"] = time.perf_counter() - t

    client = ScriptedClient([demo_response(case_name)]) if mode == DEMO else AnthropicClient()
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
        "mode": mode,
        "bundle": bundle,
        "extraction": extraction,
        "problems": problems,
        "reconciled": reconciled,
        "timings": timings,
        "model": getattr(client, "model", None),
        "tokens": (
            f"{usage.input_tokens:,} in / {usage.output_tokens:,} out" if usage else None
        ),
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
    st.divider()
    st.caption(f"Extraction schema v{SCHEMA_VERSION}")

case = CASES.get(st.session_state["case_name"])
advertiser = case.bundle.advertiser if case else DEFAULT_ADVERTISER

# ---- header ----------------------------------------------------------------

st.title("📺 Agentic Media Planner")
st.caption("Job 1: understand the request. Plan creation (Job 2) comes next.")

# ---- step 1: intake --------------------------------------------------------

st.subheader("1. Tell me what you need")
left, right = st.columns([3, 2])
with left:
    chat_text = st.text_area(
        "Your message",
        key="chat_text",
        height=110,
        disabled=(mode == DEMO),
        placeholder="e.g. I need a plan for Acme for Q1, $500,000 total. Don't run on Example News.",
    )
with right:
    pdf_path: str | None = None
    if mode == DEMO:
        st.markdown("**Brief (PDF)**")
        st.caption(f"📄 {Path(case.bundle.pdf.source).name}" if case and case.bundle.pdf else "none")
        pdf_path = case.bundle.pdf.source if case and case.bundle.pdf else None
    else:
        upload = st.file_uploader("Brief (PDF), optional", type="pdf", key="pdf_upload")
        if upload is not None:
            tmp = Path(tempfile.mkdtemp()) / upload.name
            tmp.write_bytes(upload.getvalue())
            pdf_path = str(tmp)
        elif case and case.bundle.pdf:
            pdf_path = case.bundle.pdf.source
            st.caption(f"No upload: using the example brief, 📄 {Path(pdf_path).name}")
    with st.expander("Advertiser from your session (stub)"):
        st.json(advertiser)

if st.button("Understand my request", type="primary", key="understand",
             disabled=not chat_text.strip()):
    reset_run()
    try:
        with st.spinner("Reading your message and brief..."):
            st.session_state["run"] = run_pipeline(
                mode, st.session_state["case_name"], chat_text, pdf_path, advertiser
            )
    except ModelCallError as err:
        st.error(f"Could not run the model: {err}")
    except Exception as err:  # surface anything else plainly in the demo
        st.error(f"{type(err).__name__}: {err}")

run = st.session_state.get("run")
if not run:
    st.stop()

reconciled = run["reconciled"]
timings = run["timings"]

# ---- pipeline strip --------------------------------------------------------

st.divider()
n_need = sum(r.status in NEEDS_INPUT for r in reconciled.values())
n_settled = sum(r.status == "settled" for r in reconciled.values())
cols = st.columns(4)
steps = [
    ("Gather context", "Deterministic", f"{timings['gather']*1000:.0f} ms",
     "chat + PDF text + advertiser record"),
    ("Extract", "Model" if run["mode"] == REAL else "Model (canned)",
     f"{timings['extract']:.1f} s" if run["mode"] == REAL else "replayed",
     run["tokens"] or "what each source says, with quotes"),
    ("Verify quotes", "Deterministic", f"{timings['verify']*1000:.0f} ms",
     "all quotes found in their source" if not run["problems"]
     else f"{len(run['problems'])} quote problem(s)"),
    ("Reconcile", "Deterministic", f"{timings['reconcile']*1000:.0f} ms",
     f"{n_settled} settled, {n_need} need you"),
]
for col, (name, kind, took, detail) in zip(cols, steps):
    with col.container(border=True, height=190):
        st.markdown(f"**{name}**")
        st.caption(f"{kind} · {took}")
        st.caption(detail)

# ---- step 2: what I understood --------------------------------------------

st.subheader("2. Here's what I understood")
if n_need:
    st.info(f"{n_need} item(s) need your input before I can plan. Pick an option for each.")

choices: dict[str, int | None] = {}
# Items that need the user come first (sorted() is stable, so field order is kept otherwise).
for field in sorted(FIELDS, key=lambda f: reconciled[f].status not in NEEDS_INPUT):
    result = reconciled[field]
    label = LABELS[field]
    with st.container(border=True):
        head, body = st.columns([1, 4])
        if result.status == "settled":
            head.markdown(f"✅ **{label}**")
            body.markdown(format_value(field, result.value).replace("; ", "\n\n") if
                          isinstance(result.value, list) else format_value(field, result.value))
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

resolved = resolve(reconciled, choices)

# ---- step 3: confirm -------------------------------------------------------

st.subheader("3. Confirm")
if st.button("Confirm and create plan", type="primary", key="confirm",
             disabled=not resolved.ready):
    st.session_state["confirmed"] = json.dumps(resolved.to_dict(), sort_keys=True)
if not resolved.ready:
    pending = ", ".join(LABELS[f] for f in resolved.pending)
    st.caption(f"Waiting on: {pending}")

if st.session_state.get("confirmed") == json.dumps(resolved.to_dict(), sort_keys=True):
    st.success("Confirmed. This is what the plan step receives:")
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

# ---- under the hood --------------------------------------------------------

st.divider()
with st.expander("Under the hood"):
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
