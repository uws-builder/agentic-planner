"""Brand buying guidelines, as compiled rules.

The raw guideline document is prose. It is compiled into structured rules once,
at upload, and a person reviews them (the compile step comes later; for now the
rules are fixtures). At plan time the rules are loaded deterministically by
advertiser ID. Every rule carries a verbatim quote from the document so it can be
checked and shown as evidence.

Two rule types for now: publisher exclusions and the allowed audience provider(s).
Hard rules can never be overridden by the user. Soft rules can, with a warning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RULE_TYPES = ("publisher_exclusion", "audience_provider_allow")
STRENGTHS = ("hard", "soft")


@dataclass(frozen=True)
class Rule:
    id: str
    type: str
    strength: str
    values: tuple[str, ...]
    quote: str
    section: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Rule":
        if raw.get("type") not in RULE_TYPES:
            raise ValueError(f"rule {raw.get('id')}: type must be one of {RULE_TYPES}")
        if raw.get("strength") not in STRENGTHS:
            raise ValueError(f"rule {raw.get('id')}: strength must be one of {STRENGTHS}")
        values = raw.get("values")
        if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values):
            raise ValueError(f"rule {raw.get('id')}: values must be a non-empty list of names")
        if not isinstance(raw.get("quote"), str) or not raw["quote"].strip():
            raise ValueError(f"rule {raw.get('id')}: every rule needs a quote")
        return cls(
            id=raw["id"],
            type=raw["type"],
            strength=raw["strength"],
            values=tuple(values),
            quote=raw["quote"],
            section=raw.get("section", ""),
        )


@dataclass(frozen=True)
class GuidelineSet:
    advertiser_id: str
    document_name: str
    version: str
    raw_text: str
    rules: tuple[Rule, ...]

    def rules_of(self, rule_type: str, strength: str | None = None) -> list[Rule]:
        return [
            r for r in self.rules
            if r.type == rule_type and (strength is None or r.strength == strength)
        ]

    @classmethod
    def from_dict(cls, raw: dict[str, Any], raw_text: str) -> "GuidelineSet":
        doc = raw["document"]
        return cls(
            advertiser_id=raw["advertiser_id"],
            document_name=doc["name"],
            version=doc["version"],
            raw_text=raw_text,
            rules=tuple(Rule.from_dict(r) for r in raw["rules"]),
        )
