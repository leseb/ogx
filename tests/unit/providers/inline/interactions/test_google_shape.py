# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""Validate that our Interactions adapter output matches Google's real API shape.

These tests exercise _openai_to_google() and _stream_openai_to_google() with
deterministic OpenAI inputs and compare the resulting structure against fixture
files captured from the real Google Interactions API. If Google changes their
response format, re-run scripts/capture_google_interactions_fixtures.py to
update the fixtures, then fix any failing tests.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ogx.providers.inline.interactions.config import InteractionsConfig
from ogx.providers.inline.interactions.impl import BuiltinInteractionsImpl

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict | list:
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.skip(
            f"Fixture {name} not found. Run: "
            "GEMINI_API_KEY=<key> uv run scripts/capture_google_interactions_fixtures.py"
        )
    return json.loads(path.read_text())


def _make_impl():
    impl = BuiltinInteractionsImpl(config=InteractionsConfig(), inference_api=MagicMock(), policy=[])
    impl.store = MagicMock()
    impl.store.store_interaction = AsyncMock()
    return impl


def _make_openai_response(content="4", prompt_tokens=10, completion_tokens=1):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message = MagicMock()
    resp.choices[0].message.content = content
    resp.choices[0].message.tool_calls = None
    resp.choices[0].finish_reason = "stop"
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    return resp


async def _make_openai_stream(text_chunks, prompt_tokens=7, completion_tokens=2):
    """Yield OpenAI-shaped streaming chunks for a text response."""
    for _i, text in enumerate(text_chunks):
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock()
        chunk.choices[0].delta.content = text
        chunk.choices[0].delta.tool_calls = None
        chunk.choices[0].finish_reason = None
        chunk.usage = None
        yield chunk

    # Final chunk with usage
    final = MagicMock()
    final.choices = []
    final.usage = MagicMock()
    final.usage.prompt_tokens = prompt_tokens
    final.usage.completion_tokens = completion_tokens
    yield final


class TestNonStreamingShape:
    """Verify our non-streaming response structure matches Google's fixture."""

    def test_google_fixture_top_level_fields(self):
        google = _load_fixture("google_non_streaming.json")
        expected_fields = {"id", "status", "outputs", "usage", "created", "updated", "model", "role", "object"}
        actual_fields = set(google.keys())
        missing = expected_fields - actual_fields
        assert not missing, f"Expected fields missing from Google fixture: {missing}"

    async def test_adapter_output_has_all_required_fields(self):
        """_openai_to_google produces all fields present in the Google fixture."""
        google = _load_fixture("google_non_streaming.json")
        impl = _make_impl()
        openai_resp = _make_openai_response()

        result = await impl._openai_to_google(openai_resp, "test-model", [])
        our_fields = set(result.model_dump(exclude_none=True).keys())

        required_fields = set(google.keys()) - {"created", "updated"}
        missing = required_fields - our_fields
        assert not missing, f"Adapter output missing fields that Google returns: {missing}"

    async def test_adapter_output_structure_matches_fixture(self):
        """Verify the adapter output has the same structure as the fixture."""
        google = _load_fixture("google_non_streaming.json")
        impl = _make_impl()
        openai_resp = _make_openai_response()

        result = await impl._openai_to_google(openai_resp, "test-model", [])
        result_dict = result.model_dump(exclude_none=True)

        assert result_dict["status"] == google["status"]
        assert result_dict["role"] == google["role"]
        assert result_dict["object"] == google["object"]

        text_outputs = [o for o in result_dict["outputs"] if o.get("type") == "text"]
        assert len(text_outputs) > 0, "Adapter should produce text outputs"
        assert "text" in text_outputs[0], "Text output should have 'text' field"

    async def test_adapter_usage_field_names(self):
        """Verify usage fields match Google's naming convention."""
        impl = _make_impl()
        openai_resp = _make_openai_response()

        result = await impl._openai_to_google(openai_resp, "test-model", [])
        usage = result.model_dump(exclude_none=True)["usage"]

        assert "total_input_tokens" in usage
        assert "total_output_tokens" in usage
        assert "total_tokens" in usage

    async def test_adapter_usage_values_correct(self):
        """Verify usage values are correctly translated from OpenAI format."""
        impl = _make_impl()
        openai_resp = _make_openai_response(prompt_tokens=10, completion_tokens=5)

        result = await impl._openai_to_google(openai_resp, "test-model", [])
        usage = result.usage

        assert usage.total_input_tokens == 10
        assert usage.total_output_tokens == 5
        assert usage.total_tokens == 15


class TestStreamingShape:
    """Verify our streaming adapter output matches Google's streaming fixture."""

    async def test_streaming_event_sequence(self):
        """_stream_openai_to_google produces the correct event sequence."""
        google_events = _load_fixture("google_streaming.json")
        impl = _make_impl()

        events = []
        async for event in impl._stream_openai_to_google(_make_openai_stream(["Hi", "."]), "test-model", []):
            events.append(event)

        event_types = [e.event_type for e in events]
        assert event_types[0] == "interaction.start"
        assert event_types[-1] == "interaction.complete"
        assert "content.start" in event_types
        assert "content.delta" in event_types
        assert "content.stop" in event_types

        google_event_types = [e["event_type"] for e in google_events]
        for required in [
            "InteractionStartEvent",
            "InteractionCompleteEvent",
            "ContentStart",
            "ContentDelta",
            "ContentStop",
        ]:
            assert required in google_event_types, f"Google fixture missing {required}"

    async def test_streaming_start_event_wraps_interaction(self):
        """interaction.start should wrap data in an 'interaction' object."""
        google_events = _load_fixture("google_streaming.json")
        google_start = next(e for e in google_events if e["event_type"] == "InteractionStartEvent")

        impl = _make_impl()
        events = []
        async for event in impl._stream_openai_to_google(_make_openai_stream(["test"]), "test-model", []):
            events.append(event)

        start_event = events[0]
        start_dict = start_event.model_dump(exclude_none=True)

        assert "interaction" in start_dict
        assert "id" in start_dict["interaction"]
        assert start_dict["interaction"]["object"] == google_start["data"]["interaction"]["object"]

    async def test_streaming_complete_event_structure(self):
        """interaction.complete should include usage and status=completed."""
        google_events = _load_fixture("google_streaming.json")
        google_complete = next(e for e in google_events if e["event_type"] == "InteractionCompleteEvent")

        impl = _make_impl()
        events = []
        async for event in impl._stream_openai_to_google(
            _make_openai_stream(["Hi", "."], prompt_tokens=7, completion_tokens=2), "test-model", []
        ):
            events.append(event)

        complete_event = events[-1]
        complete_dict = complete_event.model_dump(exclude_none=True)

        assert "interaction" in complete_dict
        assert complete_dict["interaction"]["status"] == google_complete["data"]["interaction"]["status"]
        assert complete_dict["interaction"]["object"] == google_complete["data"]["interaction"]["object"]
        assert "usage" in complete_dict["interaction"]

        usage = complete_dict["interaction"]["usage"]
        google_usage = google_complete["data"]["interaction"]["usage"]
        for key in ["total_input_tokens", "total_output_tokens", "total_tokens"]:
            assert key in usage, f"Adapter usage missing '{key}'"
            assert key in google_usage, f"Google fixture usage missing '{key}'"

    async def test_streaming_content_delta_text_structure(self):
        """Text deltas should have the same structure as Google's."""
        google_events = _load_fixture("google_streaming.json")
        google_text_deltas = [
            e
            for e in google_events
            if e["event_type"] == "ContentDelta" and e["data"].get("delta", {}).get("type") == "text"
        ]

        impl = _make_impl()
        events = []
        async for event in impl._stream_openai_to_google(_make_openai_stream(["Hi", "."]), "test-model", []):
            events.append(event)

        from ogx_api.interactions.models import ContentDeltaEvent

        text_deltas = [e for e in events if isinstance(e, ContentDeltaEvent) and hasattr(e.delta, "text")]

        assert len(text_deltas) == 2
        assert text_deltas[0].delta.text == "Hi"
        assert text_deltas[1].delta.text == "."

        assert len(google_text_deltas) > 0
        assert "text" in google_text_deltas[0]["data"]["delta"]

        delta_dict = text_deltas[0].model_dump(exclude_none=True)
        assert delta_dict["delta"]["type"] == google_text_deltas[0]["data"]["delta"]["type"]
