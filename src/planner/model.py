"""Model access behind one small interface.

Nothing else in the codebase imports a model SDK. To change provider or model,
add a class with `call_json` and pass it in. `ScriptedClient` is for tests and
for building the pipeline before any API spend.

Structured output uses the Messages API's `output_config.format` (JSON schema).
Forced tool choice is not supported on claude-sonnet-5-5, so we don't use it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_MODEL = "claude-sonnet-5-5"


@dataclass(frozen=True)
class OutputSpec:
    """A named JSON schema the model's reply must match."""

    name: str
    description: str
    json_schema: dict[str, Any]


class ModelClient(Protocol):
    def call_json(self, system: str, user: str, spec: OutputSpec) -> dict[str, Any]:
        """Ask the model for a reply matching `spec`; return the parsed JSON."""
        ...


class ModelCallError(RuntimeError):
    pass


@dataclass
class ScriptedClient:
    """Returns canned JSON replies, in order. Records every call for assertions."""

    responses: list[dict[str, Any]]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def call_json(self, system: str, user: str, spec: OutputSpec) -> dict[str, Any]:
        self.calls.append({"system": system, "user": user, "output": spec.name})
        if not self.responses:
            raise ModelCallError("ScriptedClient has no responses left")
        return self.responses.pop(0)


class AnthropicClient:
    """Raw Messages API call constrained to a JSON schema via structured outputs."""

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int = 16000,
        client: Any = None,
    ):
        self.model = model or os.environ.get("PLANNER_MODEL", DEFAULT_MODEL)
        self.max_tokens = max_tokens
        self.last_usage: Any = None
        if client is None:
            import anthropic  # the only place the SDK is imported

            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise ModelCallError("ANTHROPIC_API_KEY is not set")
            client = anthropic.Anthropic()
        self._client = client

    def call_json(self, system: str, user: str, spec: OutputSpec) -> dict[str, Any]:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": spec.json_schema}},
        )
        self.last_usage = getattr(response, "usage", None)
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason in ("refusal", "max_tokens"):
            raise ModelCallError(f"model stopped with {stop_reason!r}; no usable output")
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
        if text is None:
            raise ModelCallError(f"no text block in reply for {spec.name}")
        try:
            return json.loads(text)
        except json.JSONDecodeError as err:
            raise ModelCallError(f"reply for {spec.name} was not valid JSON: {err}") from err
