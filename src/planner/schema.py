"""Extraction schema: what the model must return about the user's intent.

For every field the model returns a list of *candidates*: one per statement it
found, with the source it came from and a verbatim quote as evidence. The model
does not decide what is settled or in conflict; code does that in
`planner.summarize.reconcile`. An empty list means "not stated".

Bump SCHEMA_VERSION when fields change; the schema is the contract with Job 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = "0.2"  # 0.2: target_audience is multi-valued; goal_metric descriptions tightened

SOURCES = ("chat", "pdf", "advertiser_record")

_STR = {"type": "string"}
_STR_LIST = {"type": "array", "items": {"type": "string"}}
_DATE = {"type": "string", "description": "ISO date, YYYY-MM-DD"}


@dataclass(frozen=True)
class FieldSpec:
    kind: str  # "scalar": sources that differ are a conflict. "list": values are merged.
    value_schema: dict[str, Any]
    description: str


FIELDS: dict[str, FieldSpec] = {
    "advertiser": FieldSpec("scalar", _STR, "Name of the advertiser the plan is for."),
    "budget_usd": FieldSpec(
        "scalar", {"type": "number"}, "Total budget in US dollars, as a plain number."
    ),
    "timeframe": FieldSpec(
        "scalar",
        {
            "type": "object",
            "properties": {"start": _DATE, "end": _DATE},
            "required": ["start", "end"],
            "additionalProperties": False,
        },
        "Campaign start and end dates. Only include when both can be stated as full dates.",
    ),
    "goal_metric": FieldSpec(
        "scalar",
        _STR,
        "The single metric the plan should maximize, for example unique reach, reach at a "
        "target frequency, or impressions. If a source lists several objectives, report each "
        "as its own candidate; do not pick one.",
    ),
    "target_audience": FieldSpec(
        "list",
        _STR_LIST,
        "Audience segments the plan should reach, as short descriptions. A source with "
        "primary and secondary audiences gives both.",
    ),
    "restricted_publishers": FieldSpec(
        "list", _STR_LIST, "Publishers the advertiser will not run on."
    ),
    "audience_provider_restriction": FieldSpec(
        "scalar", _STR, "Any limit on which audience data providers may be used."
    ),
    "existing_commitments": FieldSpec(
        "list", _STR_LIST, "Existing deals or volume commitments to honor."
    ),
    "buying_preferences": FieldSpec(
        "list",
        _STR_LIST,
        "Soft preferences about which supply or content to favor (for example premium "
        "supply, genre preferences). Exclude delivery requirements such as frequency caps, "
        "viewability thresholds, ad formats and supply-path rules: out of scope for now.",
    ),
}

OUTPUT_NAME = "intent_extraction"
OUTPUT_DESCRIPTION = (
    "Everything the sources say about each field. Use an empty list for a "
    "field no source mentions. Never guess."
)


class SchemaError(ValueError):
    """The model's output does not match the extraction schema."""


@dataclass(frozen=True)
class Candidate:
    source: str
    value: Any
    quote: str
    note: str | None = None


Extraction = dict[str, list[Candidate]]


def output_schema() -> dict[str, Any]:
    """JSON schema for structured outputs. Every object is closed
    (additionalProperties false) and every property is required, as strict
    schema mode expects; `note` uses an empty string for "nothing to flag"."""
    candidate_props = lambda spec: {  # noqa: E731
        "source": {"type": "string", "enum": list(SOURCES)},
        "value": spec.value_schema,
        "quote": {
            "type": "string",
            "description": "Verbatim text copied from that source that supports the value.",
        },
        "note": {
            "type": "string",
            "description": "Flag ambiguity or anything the value cannot express. Empty string if nothing to flag.",
        },
    }
    return {
        "type": "object",
        "properties": {
            name: {
                "type": "array",
                "description": spec.description,
                "items": {
                    "type": "object",
                    "properties": candidate_props(spec),
                    "required": ["source", "value", "quote", "note"],
                    "additionalProperties": False,
                },
            }
            for name, spec in FIELDS.items()
        },
        "required": list(FIELDS),
        "additionalProperties": False,
    }


def _check_value(field: str, value: Any) -> None:
    spec = FIELDS[field]
    if field == "budget_usd":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif field == "timeframe":
        ok = isinstance(value, dict) and {"start", "end"} <= value.keys()
    elif spec.kind == "list":
        ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
    else:
        ok = isinstance(value, str)
    if not ok:
        raise SchemaError(f"bad value for {field}: {value!r}")


def parse_extraction(raw: dict[str, Any]) -> Extraction:
    """Validate the model's tool input and convert it to Candidate objects."""
    unknown = set(raw) - set(FIELDS)
    if unknown:
        raise SchemaError(f"unknown fields: {sorted(unknown)}")
    result: Extraction = {}
    for field in FIELDS:
        items = raw.get(field, [])
        if not isinstance(items, list):
            raise SchemaError(f"{field} must be a list of candidates")
        candidates = []
        for item in items:
            if not isinstance(item, dict):
                raise SchemaError(f"{field}: candidate must be an object")
            if item.get("source") not in SOURCES:
                raise SchemaError(f"{field}: bad source {item.get('source')!r}")
            if not isinstance(item.get("quote"), str) or not item["quote"].strip():
                raise SchemaError(f"{field}: every candidate needs a quote")
            _check_value(field, item.get("value"))
            candidates.append(
                Candidate(
                    source=item["source"],
                    value=item["value"],
                    quote=item["quote"],
                    note=item.get("note") or None,
                )
            )
        result[field] = candidates
    return result
