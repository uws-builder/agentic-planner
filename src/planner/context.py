"""Context bundle: the output of Job 1 (assemble context).

Everything the agent will read, with the source of each piece kept explicit.
Nothing here reasons about the content; it only gathers and labels it.
Later sources (guidelines, commitments) get added as optional fields.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from planner.ingest.pdf import ExtractedDocument, PdfTextExtractor, pdf_to_text


@dataclass(frozen=True)
class ContextBundle:
    chat_text: str
    pdf: ExtractedDocument | None = None
    advertiser: dict[str, Any] | None = None

    def to_prompt_text(self) -> str:
        """Render every source under a labeled heading so provenance survives
        into the prompt (the model, and any log reader, can see where each
        piece of information came from)."""
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
) -> ContextBundle:
    """Gather the available sources into one bundle (tasks 1.1.1 to 1.1.4)."""
    if not chat_text.strip():
        raise ValueError("chat_text is empty")
    pdf = pdf_to_text(pdf_path, extractor=pdf_extractor) if pdf_path else None
    return ContextBundle(chat_text=chat_text, pdf=pdf, advertiser=advertiser)
