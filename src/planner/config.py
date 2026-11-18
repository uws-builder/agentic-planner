"""Tiny .env loader (no dependency). Real environment variables win over the file."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_env(path: Path | None = None) -> list[str]:
    """Load KEY=VALUE lines from .env into os.environ without overriding anything
    already set. Returns the names that were loaded (never the values)."""
    path = path or REPO_ROOT / ".env"
    if not path.is_file():
        return []
    loaded = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
