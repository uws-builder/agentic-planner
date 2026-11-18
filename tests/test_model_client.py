"""AnthropicClient request shape, checked with a fake SDK object (no network)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from planner.model import AnthropicClient, ModelCallError, OutputSpec
from planner.schema import output_schema

SPEC = OutputSpec("x", "an x", {"type": "object", "properties": {}})


class FakeMessages:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            content=self.content,
            stop_reason=self.stop_reason,
            usage=SimpleNamespace(input_tokens=1),
        )


def fake_sdk(content, stop_reason="end_turn"):
    messages = FakeMessages(content, stop_reason)
    return SimpleNamespace(messages=messages), messages


def text_block(payload: str):
    return SimpleNamespace(type="text", text=payload)


def test_requests_json_schema_output_and_parses_reply():
    sdk, messages = fake_sdk([text_block(json.dumps({"a": 1}))])
    client = AnthropicClient(model="m", client=sdk)
    assert client.call_json("sys", "user text", SPEC) == {"a": 1}
    kw = messages.kwargs
    assert kw["model"] == "m"
    assert kw["output_config"] == {"format": {"type": "json_schema", "schema": SPEC.json_schema}}
    assert "tool_choice" not in kw and "tools" not in kw  # forced tool choice is unsupported
    assert kw["system"] == "sys"
    assert kw["messages"] == [{"role": "user", "content": "user text"}]
    assert client.last_usage.input_tokens == 1


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_errors_on_unusable_stop_reasons(stop_reason):
    sdk, _ = fake_sdk([text_block("{}")], stop_reason=stop_reason)
    with pytest.raises(ModelCallError):
        AnthropicClient(model="m", client=sdk).call_json("s", "u", SPEC)


def test_errors_when_reply_is_not_json():
    sdk, _ = fake_sdk([text_block("not json")])
    with pytest.raises(ModelCallError):
        AnthropicClient(model="m", client=sdk).call_json("s", "u", SPEC)


def test_errors_when_no_text_block():
    sdk, _ = fake_sdk([SimpleNamespace(type="thinking")])
    with pytest.raises(ModelCallError):
        AnthropicClient(model="m", client=sdk).call_json("s", "u", SPEC)


def test_requires_api_key_when_no_client_injected(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ModelCallError):
        AnthropicClient(model="m")


def test_model_comes_from_env(monkeypatch):
    monkeypatch.setenv("PLANNER_MODEL", "some-other-model")
    sdk, _ = fake_sdk([])
    assert AnthropicClient(client=sdk).model == "some-other-model"


def _objects(schema):
    """Yield every object-typed node in a JSON schema."""
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for value in schema.values():
            yield from _objects(value)
    elif isinstance(schema, list):
        for item in schema:
            yield from _objects(item)


def test_output_schema_is_strict_compatible():
    """Every object closed, every property required (strict schema mode)."""
    objects = list(_objects(output_schema()))
    assert objects
    for obj in objects:
        assert obj.get("additionalProperties") is False
        assert set(obj["required"]) == set(obj["properties"])
