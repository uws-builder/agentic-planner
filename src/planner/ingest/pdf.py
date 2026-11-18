"""PDF to text (task 1.1.4).

The rest of the codebase only sees `ExtractedDocument`. The PDF library is
imported in exactly one place (`PypdfExtractor`), so swapping it, or moving to
a vision/model-based reader later, means adding one class that satisfies
`PdfTextExtractor` and passing it in.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ExtractedDocument:
    """Text pulled from a PDF, with enough provenance to log and debug."""

    source: str
    extractor: str
    pages: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n\n".join(self.pages)


class PdfTextExtractor(Protocol):
    """Anything that can turn a PDF file into per-page text."""

    name: str

    def extract_pages(self, path: Path) -> list[str]: ...


class PypdfExtractor:
    name = "pypdf"

    def extract_pages(self, path: Path) -> list[str]:
        from pypdf import PdfReader  # the only place pypdf is imported

        reader = PdfReader(str(path))
        return [(page.extract_text() or "").strip() for page in reader.pages]


def pdf_to_text(
    path: str | Path, extractor: PdfTextExtractor | None = None
) -> ExtractedDocument:
    """Convert a PDF to text using the given extractor (pypdf by default)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {path}")
    extractor = extractor or PypdfExtractor()
    pages = extractor.extract_pages(path)
    return ExtractedDocument(
        source=str(path), extractor=extractor.name, pages=tuple(pages)
    )
