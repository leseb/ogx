# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ogx.providers.remote.inference.nvidia.config import NVIDIAConfig
from ogx.providers.remote.inference.nvidia.nvidia import NVIDIAInferenceAdapter
from ogx.providers.utils.inference.openai_mixin import OpenAIMixin
from ogx_api import ModelType
from ogx_api.inference import RerankRequest


class MockHttpxClient:
    """Mock httpx.AsyncClient that records post calls."""

    def __init__(self, response):
        self.response = response
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    async def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.response


def create_adapter(config=None, rerank_endpoints=None):
    if config is None:
        config = NVIDIAConfig(api_key="test-key")

    adapter = NVIDIAInferenceAdapter(config=config)

    class MockModel:
        provider_resource_id = "test-model"
        metadata = {}

    adapter.model_store = AsyncMock()
    adapter.model_store.get_model = AsyncMock(return_value=MockModel())
    adapter.__provider_id__ = "nvidia"
    adapter.__provider_spec__ = MagicMock()

    if rerank_endpoints is not None:
        adapter.config.rerank_model_to_url = rerank_endpoints

    return adapter


async def test_rerank_basic_functionality():
    adapter = create_adapter()
    mock_response = httpx.Response(200, json={"rankings": [{"index": 0, "logit": 0.5}]})
    mock_client = MockHttpxClient(mock_response)

    with patch("ogx.providers.remote.inference.nvidia.nvidia.httpx.AsyncClient", return_value=mock_client):
        request = RerankRequest(model="test-model", query="test query", items=["item1", "item2"])
        result = await adapter.rerank(request)

    assert len(result.data) == 1
    assert result.data[0].index == 0
    assert result.data[0].relevance_score == 0.5

    url, kwargs = mock_client.post_calls[0]
    payload = kwargs["json"]
    assert payload["model"] == "test-model"
    assert payload["query"] == {"text": "test query"}
    assert payload["passages"] == [{"text": "item1"}, {"text": "item2"}]


async def test_missing_rankings_key():
    adapter = create_adapter()
    mock_response = httpx.Response(200, json={})
    mock_client = MockHttpxClient(mock_response)

    with patch("ogx.providers.remote.inference.nvidia.nvidia.httpx.AsyncClient", return_value=mock_client):
        request = RerankRequest(model="test-model", query="q", items=["a"])
        result = await adapter.rerank(request)

    assert len(result.data) == 0


async def test_hosted_with_endpoint():
    adapter = create_adapter(
        config=NVIDIAConfig(api_key="key"), rerank_endpoints={"test-model": "https://model.endpoint/rerank"}
    )
    mock_response = httpx.Response(200, json={"rankings": []})
    mock_client = MockHttpxClient(mock_response)

    with patch("ogx.providers.remote.inference.nvidia.nvidia.httpx.AsyncClient", return_value=mock_client):
        request = RerankRequest(model="test-model", query="q", items=["a"])
        await adapter.rerank(request)

    url, _ = mock_client.post_calls[0]
    assert url == "https://model.endpoint/rerank"


async def test_hosted_without_endpoint():
    adapter = create_adapter(
        config=NVIDIAConfig(api_key="key"),  # This creates hosted config (integrate.api.nvidia.com).
        rerank_endpoints={},  # No endpoint mapping for test-model
    )
    mock_response = httpx.Response(200, json={"rankings": []})
    mock_client = MockHttpxClient(mock_response)

    with patch("ogx.providers.remote.inference.nvidia.nvidia.httpx.AsyncClient", return_value=mock_client):
        request = RerankRequest(model="test-model", query="q", items=["a"])
        await adapter.rerank(request)

    url, _ = mock_client.post_calls[0]
    assert "https://integrate.api.nvidia.com" in url


async def test_hosted_model_not_in_endpoint_mapping():
    adapter = create_adapter(
        config=NVIDIAConfig(api_key="key"), rerank_endpoints={"other-model": "https://other.endpoint/rerank"}
    )
    mock_response = httpx.Response(200, json={"rankings": []})
    mock_client = MockHttpxClient(mock_response)

    with patch("ogx.providers.remote.inference.nvidia.nvidia.httpx.AsyncClient", return_value=mock_client):
        request = RerankRequest(model="test-model", query="q", items=["a"])
        await adapter.rerank(request)

    url, _ = mock_client.post_calls[0]
    assert "https://integrate.api.nvidia.com" in url
    assert url != "https://other.endpoint/rerank"


async def test_self_hosted_ignores_endpoint():
    adapter = create_adapter(
        config=NVIDIAConfig(base_url="http://localhost:8000", api_key=None),
        rerank_endpoints={"test-model": "https://model.endpoint/rerank"},  # This should be ignored for self-hosted.
    )
    mock_response = httpx.Response(200, json={"rankings": []})
    mock_client = MockHttpxClient(mock_response)

    with patch("ogx.providers.remote.inference.nvidia.nvidia.httpx.AsyncClient", return_value=mock_client):
        request = RerankRequest(model="test-model", query="q", items=["a"])
        await adapter.rerank(request)

    url, _ = mock_client.post_calls[0]
    assert "http://localhost:8000" in url
    assert "model.endpoint/rerank" not in url


async def test_max_num_results():
    adapter = create_adapter()
    rankings = [{"index": 0, "logit": 0.8}, {"index": 1, "logit": 0.6}]
    mock_response = httpx.Response(200, json={"rankings": rankings})
    mock_client = MockHttpxClient(mock_response)

    with patch("ogx.providers.remote.inference.nvidia.nvidia.httpx.AsyncClient", return_value=mock_client):
        request = RerankRequest(model="test-model", query="q", items=["a", "b"], max_num_results=1)
        result = await adapter.rerank(request)

    assert len(result.data) == 1
    assert result.data[0].index == 0
    assert result.data[0].relevance_score == 0.8


async def test_http_error():
    adapter = create_adapter()
    mock_response = httpx.Response(500, text="Server Error")
    mock_client = MockHttpxClient(mock_response)

    with patch("ogx.providers.remote.inference.nvidia.nvidia.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ConnectionError, match="status 500.*Server Error"):
            request = RerankRequest(model="test-model", query="q", items=["a"])
            await adapter.rerank(request)


async def test_client_error():
    adapter = create_adapter()
    mock_client = MockHttpxClient(None)

    async def raise_http_error(*args, **kwargs):
        raise httpx.ConnectError("Network error")

    mock_client.post = raise_http_error

    with patch("ogx.providers.remote.inference.nvidia.nvidia.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(ConnectionError, match="Failed to connect.*Network error"):
            request = RerankRequest(model="test-model", query="q", items=["a"])
            await adapter.rerank(request)


async def test_list_models_includes_configured_rerank_models():
    """Test that list_models adds rerank models to the dynamic model list."""
    adapter = create_adapter()
    adapter.__provider_id__ = "nvidia"
    adapter.__provider_spec__ = MagicMock()

    dynamic_ids = ["llm-1", "embedding-1"]
    with patch.object(OpenAIMixin, "list_provider_model_ids", new=AsyncMock(return_value=dynamic_ids)):
        result = await adapter.list_models()

        assert result is not None

        # Check that the rerank models are added
        model_ids = [m.identifier for m in result]
        assert "nv-rerank-qa-mistral-4b:1" in model_ids
        assert "nvidia/nv-rerankqa-mistral-4b-v3" in model_ids
        assert "nvidia/llama-3.2-nv-rerankqa-1b-v2" in model_ids

        rerank_models = [m for m in result if m.model_type == ModelType.rerank]

        assert len(rerank_models) == 3

        for m in rerank_models:
            assert m.provider_id == "nvidia"
            assert m.model_type == ModelType.rerank
            assert m.metadata == {}
            assert m.identifier in adapter._model_cache


async def test_list_provider_model_ids_has_no_duplicates():
    adapter = create_adapter()

    dynamic_ids = [
        "llm-1",
        "nvidia/nv-rerankqa-mistral-4b-v3",  # overlaps configured rerank ids
        "embedding-1",
        "llm-1",
    ]

    with patch.object(OpenAIMixin, "list_provider_model_ids", new=AsyncMock(return_value=dynamic_ids)):
        ids = list(await adapter.list_provider_model_ids())

    assert len(ids) == len(set(ids))
    assert ids.count("nvidia/nv-rerankqa-mistral-4b-v3") == 1
    assert "nv-rerank-qa-mistral-4b:1" in ids
    assert "nvidia/llama-3.2-nv-rerankqa-1b-v2" in ids


async def test_list_provider_model_ids_uses_configured_on_dynamic_failure():
    adapter = create_adapter()

    # Simulate dynamic listing failure
    with patch.object(OpenAIMixin, "list_provider_model_ids", new=AsyncMock(side_effect=Exception)):
        ids = list(await adapter.list_provider_model_ids())

    # Should still return configured rerank ids
    configured_ids = list(adapter.config.rerank_model_to_url.keys())
    assert set(ids) == set(configured_ids)
