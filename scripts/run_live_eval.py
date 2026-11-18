"""Run the extraction eval against the real model over every case in cases/.

Usage:  .venv/bin/python scripts/run_live_eval.py [case_name ...]
Needs ANTHROPIC_API_KEY. Model defaults to claude-sonnet-5-5; override with PLANNER_MODEL.
Prints per-field scores, quote problems, and the rendered summary so you can read it.
"""

from __future__ import annotations

import sys

from planner.cases import discover_case_dirs, load_case
from planner.config import load_env
from planner.evals import score
from planner.model import AnthropicClient, ModelCallError
from planner.summarize import check_quotes, extract_intent, reconcile, render_summary


def main(names: list[str]) -> int:
    load_env()
    try:
        client = AnthropicClient()
    except ModelCallError as err:
        print(f"cannot start: {err}")
        return 2
    print(f"model: {client.model}\n")
    failures = 0
    for case_dir in discover_case_dirs():
        if names and case_dir.name not in names:
            continue
        case = load_case(case_dir)
        extraction = extract_intent(case.bundle, client)
        problems = check_quotes(extraction, case.bundle)
        reconciled = reconcile(extraction)
        results = score(reconciled, case.expected)

        print(f"=== {case.name}: {case.description}")
        for field, ok in results.items():
            print(f"  {'PASS' if ok else 'FAIL'}  {field}")
        for p in problems:
            print(f"  QUOTE PROBLEM  {p.field}/{p.source}: {p.reason}: {p.quote[:80]!r}")
        print("\n" + render_summary(reconciled) + "\n")
        failures += sum(not ok for ok in results.values()) + len(problems)
    print(f"total failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
