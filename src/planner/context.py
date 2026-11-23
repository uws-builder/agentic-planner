"""Context bundle: the output of Job 1 (assemble context).

Everything the agent will read or the harness will enforce, with the source of
each piece kept explicit. Nothing here reasons about the content; it only
gathers and labels it.

Structured sources (commitments, compiled guidelines) are looked up by advertiser
ID through service interfaces. They are carried on the bundle but are NOT yet part
of the text the extraction model reads: how they enter the pipeline is decided in
the rule-composition and mapping steps.

Missing or unloadable information never blocks planning here; it becomes a warning.
Blocking is for plans that break a rule we know about (the plan validator's job).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from planner.commitments import Commitment
from planner.guidelines import GuidelineSet
from planner.ingest.pdf import ExtractedDocument, PdfTextExtractor, pdf_to_text
from planner.services import CommitmentsService, GuidelineStore, ServiceUnavailable

NO_ADVERTISER_ID = (
    "I couldn't tell which advertiser this is, so I haven't looked up commitments or brand guidelines."
)
NO_GUIDELINES = (
    "No brand buying guidelines are on file for this advertiser, so I couldn't check brand rules. "
    "Please make sure nothing in the plan breaks them."
)
GUIDELINES_UNAVAILABLE = (
    "I couldn't load this advertiser's brand guidelines, so I haven't checked brand rules. "
    "Please make sure nothing in the plan breaks them."
)
COMMITMENTS_UNAVAILABLE = (
    "I couldn't load this advertiser's existing commitments, so I haven't checked them."
)


@dataclass(frozen=True)
class ContextBundle:
    chat_text: str
    pdf: ExtractedDocument | None = None
    advertiser: dict[str, Any] | None = None
    commitments: tuple[Commitment, ...] | None = None  # None = not looked up / unavailable
    guidelines: GuidelineSet | None = None  # None = none on file / unavailable
    warnings: tuple[str, ...] = ()

    def to_prompt_text(self) -> str:
        """Render the sources the extraction model reads under labeled headings so
        provenance survives into the prompt (the model, and any log reader, can see
        where each piece of information came from)."""
        sections = [f"## Source: user chat message\n{self.chat_text.strip()}"]
        if self.pdf is not None:
            sections.append(
                f"## Source: uploaded PDF ({Path(self.pdf.source).name})\n{self.pdf.text}"
            )
        if self.advertiser is not None:
            sections.append(
                "## Source: advertiser record (system of record)\n"
                + json.dumps(self.advertiser, indent=2)
            )
        return "\n\n".join(sections)


def build_context(
    chat_text: str,
    pdf_path: str | Path | None = None,
    advertiser: dict[str, Any] | None = None,
    pdf_extractor: PdfTextExtractor | None = None,
    commitments_service: CommitmentsService | None = None,
    guideline_store: GuidelineStore | None = None,
) -> ContextBundle:
    """Gather the available sources into one bundle (tasks 1.1.1 to 1.1.6)."""
    if not chat_text.strip():
        raise ValueError("chat_text is empty")
    pdf = pdf_to_text(pdf_path, extractor=pdf_extractor) if pdf_path else None

    warnings: list[str] = []
    commitments: tuple[Commitment, ...] | None = None
    guidelines: GuidelineSet | None = None
    advertiser_id = (advertiser or {}).get("advertiser_id")
    wants_lookup = commitments_service is not None or guideline_store is not None
    if wants_lookup and not advertiser_id:
        warnings.append(NO_ADVERTISER_ID)
    elif advertiser_id:
        if commitments_service is not None:
            try:
                commitments = tuple(commitments_service.get(advertiser_id))
            except ServiceUnavailable:
                warnings.append(COMMITMENTS_UNAVAILABLE)
        if guideline_store is not None:
            try:
                guidelines = guideline_store.get(advertiser_id)
                if guidelines is None:
                    warnings.append(NO_GUIDELINES)
            except ServiceUnavailable:
                warnings.append(GUIDELINES_UNAVAILABLE)

    return ContextBundle(
        chat_text=chat_text,
        pdf=pdf,
        advertiser=advertiser,
        commitments=commitments,
        guidelines=guidelines,
        warnings=tuple(warnings),
    )
