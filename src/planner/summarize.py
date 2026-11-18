"""Extract, reconcile, render.

extract_intent  (model)          sources -> candidates with quotes
check_quotes    (deterministic)  every quote must really appear in its source
reconcile       (deterministic)  candidates -> settled / conflict / missing per field
render_summary  (deterministic)  reconciled state -> text for the user to confirm

The model never decides what is settled or in conflict, and conflicts always
reach the summary because code, not the model's wording, puts them there.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from planner.context import ContextBundle
from planner.model import ModelClient, OutputSpec
from planner.schema import (
    FIELDS,
    OUTPUT_DESCRIPTION,
    OUTPUT_NAME,
    Candidate,
    Extraction,
    output_schema,
    parse_extraction,
)

SYSTEM_PROMPT = """\
You extract a media plan request from the sources a user provided. Each source \
is labeled with a heading: "chat" is the user's typed message, "pdf" is an \
uploaded brief, and "advertiser_record" is the system record for the advertiser.

Rules:
- Report every statement a source makes about each field, one candidate per \
statement, even when two sources disagree. Do not resolve disagreements.
- Copy the supporting quote verbatim from the source. Never paraphrase it.
- Only report what a source actually states. If no source mentions a field, \
return an empty list for it. Never guess or fill gaps.
- Budget is a plain number in US dollars. Dates are ISO (YYYY-MM-DD) and need a \
full start and end; if a source gives only a rough period without dates, leave \
timeframe empty and mention it in the note of another field only if relevant.
- Use the note to flag ambiguity instead of forcing a value that doesn't fit.
- Goal is a single metric to maximize. If a source lists several objectives, \
report each one as its own candidate and leave the choice to the user.
- Buying preferences are soft preferences about which supply or content to \
favor. Leave out delivery requirements such as frequency caps, viewability \
thresholds, ad formats and supply-path rules.
"""


def extraction_output() -> OutputSpec:
    return OutputSpec(OUTPUT_NAME, OUTPUT_DESCRIPTION, output_schema())


def extract_intent(bundle: ContextBundle, client: ModelClient) -> Extraction:
    raw = client.call_json(
        system=SYSTEM_PROMPT, user=bundle.to_prompt_text(), spec=extraction_output()
    )
    return parse_extraction(raw)


# ---- quote check -----------------------------------------------------------


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def source_texts(bundle: ContextBundle) -> dict[str, str]:
    texts = {"chat": bundle.chat_text}
    if bundle.pdf is not None:
        texts["pdf"] = bundle.pdf.text
    if bundle.advertiser is not None:
        texts["advertiser_record"] = json.dumps(bundle.advertiser)
    return texts


@dataclass(frozen=True)
class QuoteProblem:
    field: str
    source: str
    quote: str
    reason: str


def check_quotes(extraction: Extraction, bundle: ContextBundle) -> list[QuoteProblem]:
    """Flag candidates whose quote is not actually in the cited source."""
    texts = {name: _norm(text) for name, text in source_texts(bundle).items()}
    problems = []
    for field, candidates in extraction.items():
        for c in candidates:
            if c.source not in texts:
                problems.append(QuoteProblem(field, c.source, c.quote, "source not provided"))
            elif _norm(c.quote) not in texts[c.source]:
                problems.append(QuoteProblem(field, c.source, c.quote, "quote not found in source"))
    return problems


# ---- reconcile -------------------------------------------------------------


@dataclass(frozen=True)
class FieldResult:
    """status is one of:
    settled    one value (or, for list fields, the merged values)
    conflict   different sources disagree on a single-valued field
    ambiguous  one source states several values for a single-valued field
    missing    no source states it
    conflict and ambiguous both need the user; the summary words them differently.
    """

    field: str
    status: str
    value: Any
    candidates: tuple[Candidate, ...]


Reconciled = dict[str, FieldResult]


def _key(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return _norm(value)
    if isinstance(value, list):
        return tuple(sorted(_key(v) for v in value))
    if isinstance(value, dict):
        return tuple(sorted((k, _key(v)) for k, v in value.items()))
    return value


def reconcile(extraction: Extraction) -> Reconciled:
    result: Reconciled = {}
    for field, spec in FIELDS.items():
        candidates = tuple(extraction.get(field, []))
        if spec.kind == "list":
            merged: list[str] = []
            seen = set()
            for c in candidates:
                for item in c.value:
                    if _key(item) not in seen:
                        seen.add(_key(item))
                        merged.append(item)
            status = "settled" if merged else "missing"
            result[field] = FieldResult(field, status, merged, candidates)
            continue
        distinct = {_key(c.value) for c in candidates}
        sources = {c.source for c in candidates}
        if not candidates:
            result[field] = FieldResult(field, "missing", None, candidates)
        elif len(distinct) == 1:
            result[field] = FieldResult(field, "settled", candidates[0].value, candidates)
        elif len(sources) >= 2:
            result[field] = FieldResult(field, "conflict", None, candidates)
        else:
            result[field] = FieldResult(field, "ambiguous", None, candidates)
    return result


NEEDS_INPUT = ("conflict", "ambiguous")


def needs_input(reconciled: Reconciled) -> dict[str, str]:
    """Fields the user must resolve, mapped to their status."""
    return {f: r.status for f, r in reconciled.items() if r.status in NEEDS_INPUT}


# ---- render ----------------------------------------------------------------

LABELS = {
    "advertiser": "Advertiser",
    "budget_usd": "Budget",
    "timeframe": "Timeframe",
    "goal_metric": "Goal",
    "target_audience": "Target audience",
    "restricted_publishers": "Restricted publishers",
    "audience_provider_restriction": "Audience data provider",
    "existing_commitments": "Existing commitments",
    "buying_preferences": "Buying preferences",
}


def _fmt(field: str, value: Any) -> str:
    if field == "budget_usd":
        return f"${value:,.0f}"
    if field == "timeframe":
        return f"{value['start']} to {value['end']}"
    if isinstance(value, list):
        return "; ".join(value)
    return str(value)


def render_summary(reconciled: Reconciled) -> str:
    lines = []
    for field, result in reconciled.items():
        label = LABELS[field]
        if result.status in NEEDS_INPUT:
            options = "; ".join(
                f"{c.source} says {_fmt(field, c.value)}" for c in result.candidates
            )
            lead = "sources disagree" if result.status == "conflict" else "several found, pick one"
            lines.append(f"- {label}: NEEDS YOUR INPUT ({lead}). {options}")
        elif result.status == "missing":
            lines.append(f"- {label}: not stated")
        else:
            sources = ", ".join(sorted({c.source for c in result.candidates}))
            lines.append(f"- {label}: {_fmt(field, result.value)} (from {sources})")
    return "\n".join(lines)
