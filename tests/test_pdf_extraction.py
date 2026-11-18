"""Evals for task 1.1.4 (PDF to text).

Code-based eval with ground truth: strings we know are in the sample RFP must
survive extraction. Whitespace is normalized before matching, so line wrapping
differences between PDF libraries don't cause false failures. If you swap the
extractor, rerun this file: it is the regression check.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from planner.ingest.pdf import ExtractedDocument, PdfTextExtractor, pdf_to_text


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# (page index, string) pairs from the sample RFP. The values the agent will
# need later (budget, flight dates, restrictions) are the ones that matter most.
KNOWN_STRINGS = [
    (0, "Summit Ridge Outdoors"),
    (0, "$1,000,000"),
    (0, "March 1 – August 22, 2027"),
    (0, "Blended CPM (all lines)"),
    (1, "five budget lines of $200,000"),
    (1, "Mon Mar 1 – Sun"),  # table cell: flight dates for line 1
    (1, "≥ 35.7M"),  # table cell: total estimated impressions
    (2, "U.S. adults 25–54"),
    (4, "Vortex Stream"),
    (4, "Hollow Peak Media"),
    (4, "Dispatch Now News Network"),
    (4, "Meridian Audience Data"),
    (5, "Compliance with restrictions and flexibility"),
]


@pytest.fixture(scope="module")
def doc(sample_rfp: Path) -> ExtractedDocument:
    return pdf_to_text(sample_rfp)


def test_page_count(doc: ExtractedDocument):
    assert len(doc.pages) == 6


def test_no_page_is_empty(doc: ExtractedDocument):
    assert all(len(page) > 200 for page in doc.pages)


@pytest.mark.parametrize("page,expected", KNOWN_STRINGS)
def test_known_string_on_expected_page(doc: ExtractedDocument, page: int, expected: str):
    assert norm(expected) in norm(doc.pages[page])


def test_extractor_is_recorded(doc: ExtractedDocument):
    assert doc.extractor == "pypdf"
    assert doc.source.endswith(".pdf")


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        pdf_to_text(tmp_path / "nope.pdf")


def test_extractor_can_be_swapped(sample_rfp: Path):
    """The pipeline depends only on the PdfTextExtractor interface."""

    class FakeExtractor:
        name = "fake"

        def extract_pages(self, path: Path) -> list[str]:
            return ["page one", "page two"]

    extractor: PdfTextExtractor = FakeExtractor()
    doc = pdf_to_text(sample_rfp, extractor=extractor)
    assert doc.extractor == "fake"
    assert doc.text == "page one\n\npage two"
