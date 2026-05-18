# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""Unit tests for previous_interaction_id conversation chaining."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ogx.providers.inline.interactions.config import InteractionsConfig
from ogx.providers.inline.interactions.impl import BuiltinInteractionsImpl
from ogx_api.interactions.models import (
    GoogleCreateInteractionRequest,
)


@pytest.fixture
def impl():
    mock_inference = AsyncMock()
    instance = BuiltinInteractionsImpl(config=InteractionsConfig(), inference_api=mock_inference, policy=[])
    instance.store = AsyncMock()
    instance.store.get_interaction = AsyncMock(return_value=None)
    instance.store.store_interaction = AsyncMock()
    return instance


class TestPreviousInteractionId:
    async def test_chaining_reconstructs_conversation(self, impl):
        """Chaining via previous_interaction_id prepends prior context."""
        stored_data = {
            "messages": [
                {"role": "system", "content": "You are a pirate."},
                {"role": "user", "content": "What is your name?"},
            ],
            "assistant_message": {"role": "assistant", "content": "Arrr, I be Captain Blackbeard!"},
        }
        impl.store.get_interaction = AsyncMock(return_value=stored_data)

        request = GoogleCreateInteractionRequest(
            model="m",
            input="Tell me more about yourself.",
            previous_interaction_id="interaction-first",
        )
        messages = await impl._build_messages(request)

        assert len(messages) == 4
        assert messages[0] == {"role": "system", "content": "You are a pirate."}
        assert messages[1] == {"role": "user", "content": "What is your name?"}
        assert messages[2] == {"role": "assistant", "content": "Arrr, I be Captain Blackbeard!"}
        assert messages[3] == {"role": "user", "content": "Tell me more about yourself."}

        impl.store.get_interaction.assert_called_once_with("interaction-first")

    async def test_chaining_with_nonexistent_id_raises(self, impl):
        """Referencing a non-existent interaction raises ValueError."""
        impl.store.get_interaction = AsyncMock(return_value=None)

        request = GoogleCreateInteractionRequest(
            model="m",
            input="Hello",
            previous_interaction_id="interaction-does-not-exist",
        )
        with pytest.raises(ValueError, match="not found"):
            await impl._build_messages(request)

    async def test_interaction_stored_after_non_streaming(self, impl):
        """Non-streaming responses are persisted via the store."""
        openai_resp = MagicMock()
        openai_resp.choices = [MagicMock()]
        openai_resp.choices[0].message = MagicMock()
        openai_resp.choices[0].message.content = "Hello!"
        openai_resp.choices[0].message.tool_calls = None
        openai_resp.choices[0].finish_reason = "stop"
        openai_resp.usage = MagicMock()
        openai_resp.usage.prompt_tokens = 10
        openai_resp.usage.completion_tokens = 5

        messages = [{"role": "user", "content": "Hi"}]
        result = await impl._openai_to_google(openai_resp, "m", messages)

        impl.store.store_interaction.assert_called_once()
        call_kwargs = impl.store.store_interaction.call_args.kwargs
        assert call_kwargs["interaction_id"] == result.id
        assert call_kwargs["model"] == "m"
        assert call_kwargs["messages"] == messages
        assert call_kwargs["assistant_message"] == {"role": "assistant", "content": "Hello!"}

    async def test_interaction_stored_after_streaming(self, impl):
        """Streaming responses are persisted after the stream completes."""
        chunks = []
        for text in ["Hello", " world"]:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta = MagicMock()
            chunk.choices[0].delta.content = text
            chunk.choices[0].delta.tool_calls = None
            chunk.choices[0].finish_reason = None
            chunk.usage = None
            chunks.append(chunk)

        async def mock_stream():
            for c in chunks:
                yield c

        messages = [{"role": "user", "content": "Hi"}]
        events = []
        async for event in impl._stream_openai_to_google(mock_stream(), "m", messages):
            events.append(event)

        impl.store.store_interaction.assert_called_once()
        call_kwargs = impl.store.store_interaction.call_args.kwargs
        assert call_kwargs["messages"] == messages
        assert call_kwargs["assistant_message"] == {"role": "assistant", "content": "Hello world"}

    async def test_multi_hop_chaining(self, impl):
        """Chain through multiple interactions preserving full history."""
        first_stored = {
            "messages": [{"role": "user", "content": "Hi"}],
            "assistant_message": {"role": "assistant", "content": "Hello!"},
        }

        impl.store.get_interaction = AsyncMock(return_value=first_stored)

        request2 = GoogleCreateInteractionRequest(
            model="m",
            input="How are you?",
            previous_interaction_id="interaction-1",
        )
        messages2 = await impl._build_messages(request2)

        assert len(messages2) == 3
        assert messages2[0] == {"role": "user", "content": "Hi"}
        assert messages2[1] == {"role": "assistant", "content": "Hello!"}
        assert messages2[2] == {"role": "user", "content": "How are you?"}

        second_stored = {
            "messages": messages2,
            "assistant_message": {"role": "assistant", "content": "I'm doing well!"},
        }
        impl.store.get_interaction = AsyncMock(return_value=second_stored)

        request3 = GoogleCreateInteractionRequest(
            model="m",
            input="Great to hear.",
            previous_interaction_id="interaction-2",
        )
        messages3 = await impl._build_messages(request3)

        assert len(messages3) == 5
        assert messages3[0] == {"role": "user", "content": "Hi"}
        assert messages3[1] == {"role": "assistant", "content": "Hello!"}
        assert messages3[2] == {"role": "user", "content": "How are you?"}
        assert messages3[3] == {"role": "assistant", "content": "I'm doing well!"}
        assert messages3[4] == {"role": "user", "content": "Great to hear."}

    async def test_chaining_preserves_tool_calls(self, impl):
        """Tool calls in assistant messages are preserved when chaining."""
        stored_data = {
            "messages": [
                {"role": "user", "content": "What's the weather in SF?"},
            ],
            "assistant_message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"location": "San Francisco"}',
                        },
                    }
                ],
            },
        }
        impl.store.get_interaction = AsyncMock(return_value=stored_data)

        request = GoogleCreateInteractionRequest(
            model="m",
            input="Thanks!",
            previous_interaction_id="interaction-with-tools",
        )
        messages = await impl._build_messages(request)

        assert len(messages) == 3
        assert messages[0] == {"role": "user", "content": "What's the weather in SF?"}
        assert messages[1] == stored_data["assistant_message"]
        assert messages[1]["tool_calls"][0]["id"] == "call_abc123"
        assert messages[1]["tool_calls"][0]["function"]["name"] == "get_weather"
        assert messages[2] == {"role": "user", "content": "Thanks!"}

    async def test_tool_calls_stored_after_non_streaming(self, impl):
        """Non-streaming tool call responses are persisted correctly."""
        tool_call = MagicMock()
        tool_call.id = "call_xyz789"
        tool_call.type = "function"
        tool_call.function = MagicMock()
        tool_call.function.name = "search"
        tool_call.function.arguments = '{"query": "test"}'
        tool_call.model_dump = MagicMock(
            return_value={
                "id": "call_xyz789",
                "type": "function",
                "function": {"name": "search", "arguments": '{"query": "test"}'},
            }
        )

        openai_resp = MagicMock()
        openai_resp.choices = [MagicMock()]
        openai_resp.choices[0].message = MagicMock()
        openai_resp.choices[0].message.content = None
        openai_resp.choices[0].message.tool_calls = [tool_call]
        openai_resp.choices[0].finish_reason = "tool_calls"
        openai_resp.usage = MagicMock()
        openai_resp.usage.prompt_tokens = 10
        openai_resp.usage.completion_tokens = 5

        messages = [{"role": "user", "content": "Search for test"}]
        await impl._openai_to_google(openai_resp, "m", messages)

        impl.store.store_interaction.assert_called_once()
        call_kwargs = impl.store.store_interaction.call_args.kwargs
        assistant_msg = call_kwargs["assistant_message"]
        assert assistant_msg["role"] == "assistant"
        assert len(assistant_msg["tool_calls"]) == 1
        assert assistant_msg["tool_calls"][0]["id"] == "call_xyz789"
        assert assistant_msg["tool_calls"][0]["function"]["name"] == "search"

    async def test_legacy_output_text_fallback(self, impl):
        """Legacy stored interactions with only output_text still work."""
        stored_data = {
            "messages": [{"role": "user", "content": "Hello"}],
            "output_text": "Hi there!",
        }
        impl.store.get_interaction = AsyncMock(return_value=stored_data)

        request = GoogleCreateInteractionRequest(
            model="m",
            input="How are you?",
            previous_interaction_id="interaction-legacy",
        )
        messages = await impl._build_messages(request)

        assert len(messages) == 3
        assert messages[1] == {"role": "assistant", "content": "Hi there!"}
