"""Canned model replies for the example cases.

What a perfect model would return for the two Summit Ridge cases. The UI's demo
mode replays these so illustrations are free and repeatable; the tests use the
same data to prove the pipeline wiring. They are not a measure of model quality.
"""

from __future__ import annotations

from typing import Any

DEMO_CASES = ("summit_ridge_clean", "summit_ridge_budget_conflict")

PUBLISHERS = ["Vortex Stream", "Hollow Peak Media", "Dispatch Now News Network"]
TIMEFRAME = {"start": "2027-03-01", "end": "2027-08-22"}


def demo_response(case_name: str) -> dict[str, Any]:
    if case_name not in DEMO_CASES:
        raise KeyError(f"no canned response for case {case_name!r}")
    chat_budget = 800000 if "budget_conflict" in case_name else 1000000
    chat_quote = "$800,000" if chat_budget == 800000 else "$1,000,000"
    return {
        "advertiser": [
            {"source": "chat", "value": "Summit Ridge Outdoors", "quote": "Summit Ridge Outdoors"},
            {"source": "pdf", "value": "Summit Ridge Outdoors", "quote": "Summit Ridge Outdoors"},
            {"source": "advertiser_record", "value": "Summit Ridge Outdoors", "quote": "Summit Ridge Outdoors"},
        ],
        "budget_usd": [
            {"source": "chat", "value": chat_budget, "quote": chat_quote},
            {"source": "pdf", "value": 1000000, "quote": "$1,000,000"},
        ],
        "timeframe": [
            {"source": "pdf", "value": TIMEFRAME, "quote": "March 1 – August 22, 2027"},
        ],
        "goal_metric": [
            {
                "source": "pdf",
                "value": "reach and frequency",
                "quote": "Build reach and frequency against the target audience",
            },
            {
                "source": "pdf",
                "value": "qualified site traffic and purchases",
                "quote": "Drive qualified traffic and purchases to summitridgeoutdoors.example during each flight",
            },
        ],
        "target_audience": [
            {
                "source": "pdf",
                "value": ["Primary: U.S. adults 25-54 who hike, camp or spend regular time outdoors"],
                "quote": "The primary audience is U.S. adults 25–54 who hike, camp or spend regular time outdoors",
            },
            {
                "source": "pdf",
                "value": ["Secondary: adults 55-64"],
                "quote": "Adults 55–64",
            },
        ],
        "restricted_publishers": [
            {"source": "chat", "value": ["Vortex Stream"], "quote": "Don't run on Vortex Stream"},
            {
                "source": "pdf",
                "value": PUBLISHERS,
                "quote": "No ads on Vortex Stream, Hollow Peak Media or Dispatch Now News Network",
            },
        ],
        "audience_provider_restriction": [
            {
                "source": "pdf",
                "value": "Meridian Audience Data only, for third-party audience data",
                "quote": "may use only that provider for third-party audience data",
            }
        ],
        "existing_commitments": [],
        "buying_preferences": [
            {
                "source": "pdf",
                "value": ["Brand-safe, family-appropriate content at or below TV-PG"],
                "quote": "Brand-safe, family-appropriate content at or below a TV-PG rating",
            }
        ],
    }
