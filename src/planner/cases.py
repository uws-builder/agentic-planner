"""Test cases: one folder per scenario, so adding a test means adding a folder.

Layout:  cases/<name>/case.json

case.json fields:
  description  what this case is for
  chat         the user's chat message
  pdf          optional path to a PDF (relative to the case folder, else to the repo root)
  advertiser   optional advertiser record (the stub for the session's advertiser)
  expected     ground truth for evals (drafted by Claude unless "draft" is false; edit freely)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from planner.context import ContextBundle, build_context
from planner.ingest.pdf import PdfTextExtractor
from planner.services import FakeCommitments, FakeGuidelines

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / "cases"


@dataclass(frozen=True)
class Case:
    name: str
    description: str
    bundle: ContextBundle
    expected: dict[str, Any]


def _resolve_pdf(case_dir: Path, pdf: str) -> Path:
    for base in (case_dir, REPO_ROOT):
        candidate = base / pdf
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"PDF '{pdf}' not found relative to {case_dir} or {REPO_ROOT}")


def load_case(case_dir: Path, pdf_extractor: PdfTextExtractor | None = None) -> Case:
    raw = json.loads((case_dir / "case.json").read_text())
    pdf_path = _resolve_pdf(case_dir, raw["pdf"]) if raw.get("pdf") else None
    bundle = build_context(
        chat_text=raw["chat"],
        pdf_path=pdf_path,
        advertiser=raw.get("advertiser"),
        pdf_extractor=pdf_extractor,
        commitments_service=FakeCommitments(),
        guideline_store=FakeGuidelines(),
    )
    return Case(
        name=case_dir.name,
        description=raw.get("description", ""),
        bundle=bundle,
        expected=raw.get("expected", {}),
    )


def discover_case_dirs(root: Path = CASES_DIR) -> list[Path]:
    return sorted(p.parent for p in root.glob("*/case.json"))
