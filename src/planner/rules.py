"""Rule composition and the plan validator. Deterministic code; no model.

Constraints compose by restriction:
  - Exclusions are a union: a publisher excluded by any source is excluded.
  - Audience-provider allow-lists intersect. An empty intersection can't be
    satisfied, so it is a blocker the user must resolve.
  - Hard guideline rules can't be overridden. Soft ones can, with a warning.
  - A user can tighten the brand's rules but never loosen a hard one.

Blocking is only for known conflicts: a hard rule that something we were asked to
do would break. Missing or unloadable information is a warning, handled earlier
when the context is assembled.

Notices are what the user is told: info (applied for you), warning (a soft rule
was overridden), blocker (can't plan until this is resolved).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from planner.commitments import Commitment
from planner.guidelines import GuidelineSet, Rule
from planner.names import norm_name

INFO, WARNING, BLOCKER = "info", "warning", "blocker"


@dataclass(frozen=True)
class Notice:
    level: str
    code: str
    text: str


@dataclass(frozen=True)
class Exclusion:
    publisher: str
    strength: str  # "hard" | "soft"
    sources: tuple[str, ...]
    overridden: bool = False  # soft rules only

    @property
    def enforced(self) -> bool:
        return not self.overridden


@dataclass(frozen=True)
class Constraints:
    exclusions: tuple[Exclusion, ...]
    allowed_providers: tuple[str, ...] | None  # None = no allow-list; () = nothing satisfies
    notices: tuple[Notice, ...]

    @property
    def blockers(self) -> list[Notice]:
        return [n for n in self.notices if n.level == BLOCKER]

    @property
    def warnings(self) -> list[Notice]:
        return [n for n in self.notices if n.level == WARNING]

    def enforced_names(self) -> set[str]:
        """Normalized names of publishers the plan must leave out right now."""
        return {norm_name(e.publisher) for e in self.exclusions if e.enforced}

    def soft_exclusions(self) -> list[Exclusion]:
        return [e for e in self.exclusions if e.strength == "soft"]

    def hard_exclusions(self) -> list[Exclusion]:
        return [e for e in self.exclusions if e.strength == "hard"]


def _where(rule: Rule) -> str:
    return f"brand guidelines §{rule.section}" if rule.section else f"brand guidelines ({rule.id})"


def _join(items: Iterable[str]) -> str:
    items = list(items)
    return ", ".join(items[:-1]) + f" and {items[-1]}" if len(items) > 1 else (items[0] if items else "")


def _money(amount: float) -> str:
    return f"${amount:,.0f}"


def compose_constraints(
    *,
    guidelines: GuidelineSet | None,
    user_exclusions: Iterable[str] = (),
    user_allowed_providers: Iterable[str] | None = None,
    requested_publishers: Iterable[str] = (),
    overrides: Iterable[str] = (),
    commitments: Iterable[Commitment] = (),
) -> Constraints:
    """Combine brand guidelines with what the user said into the rules the plan must follow.

    user_exclusions         publishers the user (chat or RFP) said not to run on
    user_allowed_providers  audience providers the user said to use (None = no statement)
    requested_publishers    publishers the user explicitly asked to include
    overrides               soft-rule publishers the user chose to include anyway
    commitments             commitments active in the plan's timeframe
    """
    notices: list[Notice] = []

    # ---- publisher exclusions: union, strongest strength wins ----
    entries: dict[str, dict[str, Any]] = {}

    def add(name: str, strength: str, source: str) -> None:
        key = norm_name(name)
        entry = entries.get(key)
        if entry is None:
            entries[key] = {"publisher": name, "strength": strength, "sources": [source], "overridden": False}
            return
        if source not in entry["sources"]:
            entry["sources"].append(source)
        if strength == "hard":
            entry["strength"] = "hard"

    if guidelines is not None:
        for rule in guidelines.rules_of("publisher_exclusion"):
            for name in rule.values:
                add(name, rule.strength, _where(rule))
    for name in user_exclusions:
        add(name, "hard", "your request")

    # ---- the user asks to include something, or overrides a soft rule ----
    wanted = {norm_name(n): n for n in requested_publishers}
    chosen = {norm_name(n) for n in overrides}
    for key, entry in entries.items():
        if key not in wanted and key not in chosen:
            continue
        where = _join(entry["sources"])
        if entry["strength"] == "hard":
            if key in wanted:
                notices.append(Notice(INFO, "request_blocked_by_hard_rule",
                    f"You asked for {entry['publisher']}, but {where} exclude it, so I left it out."))
        else:
            entry["overridden"] = True
            lead = "You asked for" if key in wanted else "You chose to include"
            notices.append(Notice(WARNING, "soft_rule_overridden",
                f"{lead} {entry['publisher']}, which {where} say to avoid. I've included it."))

    # ---- commitments against exclusions ----
    for c in commitments:
        entry = entries.get(norm_name(c.publisher))
        if entry is None:
            continue
        where = _join(entry["sources"])
        deal = f"{c.deal_type} commitment ({_money(c.remaining_usd)} remaining)"
        if entry["strength"] == "hard":
            notices.append(Notice(BLOCKER, "commitment_vs_hard_exclusion",
                f"You have a {deal} with {c.publisher}, but {where} exclude it. "
                "I can't honor both, so one of them needs to change before I can plan."))
        elif not entry["overridden"]:
            entry["overridden"] = True
            notices.append(Notice(WARNING, "commitment_vs_soft_exclusion",
                f"You have a {deal} with {c.publisher}, which {where} say to avoid. "
                f"I've included {c.publisher} to honor the commitment."))

    exclusions = tuple(
        Exclusion(e["publisher"], e["strength"], tuple(e["sources"]), e["overridden"])
        for e in sorted(entries.values(), key=lambda e: (e["strength"] != "hard", norm_name(e["publisher"])))
    )

    # ---- audience providers: hard allow-lists intersect ----
    allow_sets: list[tuple[str, list[str]]] = []
    if guidelines is not None:
        for rule in guidelines.rules_of("audience_provider_allow"):
            if rule.strength == "hard":
                allow_sets.append((_where(rule), list(rule.values)))
            else:
                notices.append(Notice(INFO, "soft_provider_preference",
                    f"{_where(rule).capitalize()} prefer {_join(rule.values)} for audience data, "
                    "but other providers can be used."))
    user_providers = list(user_allowed_providers) if user_allowed_providers else []
    if user_providers:
        allow_sets.append(("your request", user_providers))

    allowed: tuple[str, ...] | None = None
    if allow_sets:
        keys = set.intersection(*({norm_name(n) for n in names} for _, names in allow_sets))
        allowed = tuple(n for n in allow_sets[0][1] if norm_name(n) in keys)
        if not allowed:
            parts = "; ".join(f"{src} allow only {_join(names)}" if src != "your request"
                              else f"your request names only {_join(names)}"
                              for src, names in allow_sets)
            notices.append(Notice(BLOCKER, "provider_allowlists_disjoint",
                f"The audience data rules can't all be met: {parts}. "
                "No provider satisfies every one, so this needs to be resolved before I can plan."))
        elif user_providers and len(allow_sets) > 1:
            dropped = [n for n in user_providers if norm_name(n) not in keys]
            if dropped:
                notices.append(Notice(INFO, "provider_narrowed",
                    f"Brand guidelines allow only {_join(allowed)} for audience data, "
                    f"so I'm not using {_join(dropped)}."))

    return Constraints(exclusions=exclusions, allowed_providers=allowed, notices=tuple(notices))


# ---- the validator ---------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    publisher: str
    reason: str


def validate_plan(plan: Any, constraints: Constraints) -> list[Violation]:
    """Check a finished plan against the rules currently enforced. Independent of how the
    plan was built: whatever produced it (code, optimizer, model), it can't ship with a
    publisher the rules exclude."""
    enforced = {norm_name(e.publisher): e for e in constraints.exclusions if e.enforced}
    violations = []
    for line in plan.lines:
        entry = enforced.get(norm_name(line.publisher))
        if entry is not None:
            kind = "excluded" if entry.strength == "hard" else "set to be avoided"
            violations.append(Violation(line.publisher,
                f"{line.publisher} is {kind} by {_join(entry.sources)}."))
    return violations
