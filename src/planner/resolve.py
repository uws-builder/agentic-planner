"""Apply the user's choices to the reconciled result (the confirmation step).

Settled fields pass through. Fields that need the user (conflict or ambiguous)
become one option per distinct value, labeled with the sources that said it.
Until every such field has a choice, the result is not ready. The resolved
values are the handoff to Job 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from planner.schema import FIELDS, SCHEMA_VERSION
from planner.summarize import NEEDS_INPUT, FieldResult, Reconciled, _key, format_value


@dataclass(frozen=True)
class Option:
    label: str
    value: Any
    sources: tuple[str, ...]


def options_for(result: FieldResult) -> list[Option]:
    """One option per distinct candidate value, in the order first stated."""
    grouped: dict[Any, tuple[Any, list[str]]] = {}
    for c in result.candidates:
        _, sources = grouped.setdefault(_key(c.value), (c.value, []))
        sources.append(c.source)
    options = []
    for value, sources in grouped.values():
        srcs = tuple(dict.fromkeys(sources))
        label = f"{format_value(result.field, value)}  ({', '.join(srcs)})"
        options.append(Option(label, value, srcs))
    return options


@dataclass(frozen=True)
class Resolved:
    values: dict[str, Any]
    how: dict[str, str]
    pending: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.pending

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "values": self.values, "how": self.how}


def resolve(reconciled: Reconciled, choices: dict[str, int | None]) -> Resolved:
    """`choices` maps a field to the index of the chosen option (or None)."""
    values: dict[str, Any] = {}
    how: dict[str, str] = {}
    pending: list[str] = []
    for field, result in reconciled.items():
        if result.status == "settled":
            values[field] = result.value
            how[field] = "from " + ", ".join(sorted({c.source for c in result.candidates}))
        elif result.status == "missing":
            values[field] = [] if FIELDS[field].kind == "list" else None
            how[field] = "not stated"
        else:
            assert result.status in NEEDS_INPUT
            options = options_for(result)
            index = choices.get(field)
            if index is None or not 0 <= index < len(options):
                pending.append(field)
                values[field] = None
                how[field] = "waiting for you"
            else:
                values[field] = options[index].value
                how[field] = "chosen by you (" + ", ".join(options[index].sources) + ")"
    return Resolved(values=values, how=how, pending=tuple(pending))
