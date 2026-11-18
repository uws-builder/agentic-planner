from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def sample_rfp() -> Path:
    """The sample streaming TV RFP used as the PDF fixture."""
    path = ROOT / "Streaming TV Media Plan RFP (Sample).pdf"
    assert path.is_file(), f"missing fixture: {path}"
    return path
