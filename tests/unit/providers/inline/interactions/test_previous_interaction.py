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
            "output_text": "Arrr, I be Captain Blackbeard!",
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
        assert call_kwargs["output_text"] == "Hello!"

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
        assert call_kwargs["output_text"] == "Hello world"

    async def test_chaining_with_tool_calls_uses_output_message(self, impl):
        """Chaining includes tool_calls from the prior assistant turn."""
        stored_data = {
            "messages": [
                {"role": "user", "content": "What is the weather in Paris?"},
            ],
            "output_text": "",
            "output_message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"location": "Paris"}',
                        },
                    }
                ],
            },
        }
        impl.store.get_interaction = AsyncMock(return_value=stored_data)

        request = GoogleCreateInteractionRequest(
            model="m",
            input="Never mind, how about London?",
            previous_interaction_id="interaction-tool",
        )
        messages = await impl._build_messages(request)

        assert len(messages) == 3
        assert messages[0] == {"role": "user", "content": "What is the weather in Paris?"}
        # The assistant message must carry tool_calls, not just text
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] is None
        assert len(messages[1]["tool_calls"]) == 1
        assert messages[1]["tool_calls"][0]["function"]["name"] == "get_weather"
        assert messages[2] == {"role": "user", "content": "Never mind, how about London?"}

    async def test_chaining_falls_back_to_output_text_when_no_output_message(self, impl):
        """Legacy stored interactions without output_message still work."""
        stored_data = {
            "messages": [
                {"role": "user", "content": "Hi"},
            ],
            "output_text": "Hello there!",
            # No output_message key -- legacy format
        }
        impl.store.get_interaction = AsyncMock(return_value=stored_data)

        request = GoogleCreateInteractionRequest(
            model="m",
            input="How are you?",
            previous_interaction_id="interaction-legacy",
        )
        messages = await impl._build_messages(request)

        assert len(messages) == 3
        assert messages[1] == {"role": "assistant", "content": "Hello there!"}

    async def test_non_streaming_stores_output_message_with_tool_calls(self, impl):
        """Non-streaming responses store the full assistant message including tool_calls."""
        openai_resp = MagicMock()
        openai_resp.choices = [MagicMock()]
        openai_resp.choices[0].message = MagicMock()
        openai_resp.choices[0].message.content = None
        tc = MagicMock()
        tc.id = "call_xyz"
        tc.function = MagicMock()
        tc.function.name = "get_weather"
        tc.function.arguments = '{"location": "Paris"}'
        openai_resp.choices[0].message.tool_calls = [tc]
        openai_resp.choices[0].finish_reason = "tool_calls"
        openai_resp.usage = MagicMock()
        openai_resp.usage.prompt_tokens = 10
        openai_resp.usage.completion_tokens = 5

        messages = [{"role": "user", "content": "Weather in Paris?"}]
        await impl._openai_to_google(openai_resp, "m", messages)

        call_kwargs = impl.store.store_interaction.call_args.kwargs
        output_msg = call_kwargs["output_message"]
        assert output_msg["role"] == "assistant"
        assert len(output_msg["tool_calls"]) == 1
        assert output_msg["tool_calls"][0]["id"] == "call_xyz"
        assert output_msg["tool_calls"][0]["function"]["name"] == "get_weather"

    async def test_streaming_stores_output_message_with_tool_calls(self, impl):
        """Streaming responses store the full assistant message including tool_calls."""
        chunks = []

        # First chunk: tool call start
        tc_delta_start = MagicMock()
        tc_delta_start.index = 0
        tc_delta_start.id = "call_stream_abc"
        tc_delta_start.function = MagicMock()
        tc_delta_start.function.name = "search"
        tc_delta_start.function.arguments = '{"q":'

        chunk1 = MagicMock()
        chunk1.choices = [MagicMock()]
        chunk1.choices[0].delta = MagicMock()
        chunk1.choices[0].delta.content = None
        chunk1.choices[0].delta.tool_calls = [tc_delta_start]
        chunk1.choices[0].finish_reason = None
        chunk1.usage = None
        chunks.append(chunk1)

        # Second chunk: tool call arguments continuation
        tc_delta_args = MagicMock()
        tc_delta_args.index = 0
        tc_delta_args.id = None
        tc_delta_args.function = MagicMock()
        tc_delta_args.function.name = None
        tc_delta_args.function.arguments = ' "hello"}'

        chunk2 = MagicMock()
        chunk2.choices = [MagicMock()]
        chunk2.choices[0].delta = MagicMock()
        chunk2.choices[0].delta.content = None
        chunk2.choices[0].delta.tool_calls = [tc_delta_args]
        chunk2.choices[0].finish_reason = None
        chunk2.usage = None
        chunks.append(chunk2)

        async def mock_stream():
            for c in chunks:
                yield c

        messages = [{"role": "user", "content": "Search for hello"}]
        events = []
        async for event in impl._stream_openai_to_google(mock_stream(), "m", messages):
            events.append(event)

        call_kwargs = impl.store.store_interaction.call_args.kwargs
        output_msg = call_kwargs["output_message"]
        assert output_msg["role"] == "assistant"
        assert output_msg["content"] is None  # No text content
        assert len(output_msg["tool_calls"]) == 1
        assert output_msg["tool_calls"][0]["id"] == "call_stream_abc"
        assert output_msg["tool_calls"][0]["function"]["name"] == "search"
        assert output_msg["tool_calls"][0]["function"]["arguments"] == '{"q": "hello"}'

    async def test_multi_hop_chaining(self, impl):
        """Chain through multiple interactions preserving full history."""
        first_stored = {
            "messages": [{"role": "user", "content": "Hi"}],
            "output_text": "Hello!",
            "output_message": {"role": "assistant", "content": "Hello!"},
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
            "output_text": "I'm doing well!",
            "output_message": {"role": "assistant", "content": "I'm doing well!"},
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
