"""Service interfaces for the data we look up by advertiser ID, and fakes for them.

The fakes are plain deterministic code reading fixtures from
fixtures/advertisers/<advertiser_id>/. They are never LLM-generated, so a
failing eval can only be the agent's fault. When a real backend exists it
replaces a fake behind the same interface.

Fault injection: a fake built with fail=True raises ServiceUnavailable, so
error handling can be tested without a real outage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from planner.commitments import Commitment
from planner.guidelines import GuidelineSet

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures" / "advertisers"


class ServiceUnavailable(RuntimeError):
    """The backing service could not be reached or its data could not be loaded."""


class CommitmentsService(Protocol):
    def get(self, advertiser_id: str) -> list[Commitment]:
        """Commitments on file for the advertiser (empty if none)."""
        ...


class GuidelineStore(Protocol):
    def get(self, advertiser_id: str) -> GuidelineSet | None:
        """The advertiser's compiled guidelines, or None if none are on file."""
        ...


class FakeCommitments:
    def __init__(self, root: Path = FIXTURES, fail: bool = False):
        self.root, self.fail = root, fail

    def get(self, advertiser_id: str) -> list[Commitment]:
        if self.fail:
            raise ServiceUnavailable("commitments service is down")
        path = self.root / advertiser_id / "commitments.json"
        if not path.is_file():
            return []
        try:
            return [Commitment.from_dict(r) for r in json.loads(path.read_text())]
        except (ValueError, KeyError) as err:
            raise ServiceUnavailable(f"commitments for {advertiser_id} could not be loaded: {err}") from err


class FakeGuidelines:
    def __init__(self, root: Path = FIXTURES, fail: bool = False):
        self.root, self.fail = root, fail

    def get(self, advertiser_id: str) -> GuidelineSet | None:
        if self.fail:
            raise ServiceUnavailable("guideline store is down")
        rules_path = self.root / advertiser_id / "guidelines.json"
        if not rules_path.is_file():
            return None
        text_path = self.root / advertiser_id / "guidelines.txt"
        try:
            raw_text = text_path.read_text() if text_path.is_file() else ""
            return GuidelineSet.from_dict(json.loads(rules_path.read_text()), raw_text)
        except (ValueError, KeyError) as err:
            raise ServiceUnavailable(f"guidelines for {advertiser_id} could not be loaded: {err}") from err
