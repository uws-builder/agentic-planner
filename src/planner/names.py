"""Name matching helper shared by plan, rules and the UI."""

from __future__ import annotations

import re


def norm_name(text: str) -> str:
    """Case- and whitespace-insensitive key for matching names."""
    return re.sub(r"\s+", " ", text).strip().lower()
