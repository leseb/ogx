# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""Unit tests for batch orphan reconciliation on provider restart."""

import time
from unittest.mock import AsyncMock, MagicMock

from ogx.core.storage.datatypes import SqlStoreReference
from ogx.providers.inline.batches.reference.batches import ReferenceBatchesImpl
from ogx.providers.inline.batches.reference.config import ReferenceBatchesImplConfig
from ogx_api import BatchObject, PaginatedResponse


async def test_reconcile_orphaned_batches_on_initialize():
    """Test that orphaned batches are reconciled on provider initialization."""
    # Create mock dependencies
    config = ReferenceBatchesImplConfig(sqlstore=SqlStoreReference(backend="sql_default", table_name="batches"))
    inference_api = MagicMock()
    files_api = MagicMock()
    models_api = MagicMock()
    sql_store = AsyncMock()

    # Mock the create_table call
    sql_store.create_table = AsyncMock()

    # Create orphaned batch data
    current_time = int(time.time())
    orphaned_batches = [
        {
            "id": "batch_validating",
            "status": "validating",
            "batch_data": BatchObject(
                id="batch_validating",
                object="batch",
                endpoint="/v1/chat/completions",
                input_file_id="file_123",
                completion_window="24h",
                status="validating",
                created_at=current_time - 3600,
            ).model_dump(),
        },
        {
            "id": "batch_in_progress",
            "status": "in_progress",
            "batch_data": BatchObject(
                id="batch_in_progress",
                object="batch",
                endpoint="/v1/chat/completions",
                input_file_id="file_456",
                completion_window="24h",
                status="in_progress",
                created_at=current_time - 1800,
                request_counts={"total": 10, "completed": 5, "failed": 0},
            ).model_dump(),
        },
        {
            "id": "batch_cancelling",
            "status": "cancelling",
            "batch_data": BatchObject(
                id="batch_cancelling",
                object="batch",
                endpoint="/v1/chat/completions",
                input_file_id="file_789",
                completion_window="24h",
                status="cancelling",
                created_at=current_time - 900,
                cancelling_at=current_time - 60,
            ).model_dump(),
        },
    ]

    # Mock fetch_all to return orphaned batches for each non-terminal status
    def mock_fetch_all(table, where=None, **kwargs):
        if where and "status" in where:
            status = where["status"]
            matching = [b for b in orphaned_batches if b["status"] == status]
            return PaginatedResponse(data=matching, has_more=False)
        return PaginatedResponse(data=[], has_more=False)

    sql_store.fetch_all = AsyncMock(side_effect=mock_fetch_all)
    sql_store.update = AsyncMock()

    # Create the batches provider
    provider = ReferenceBatchesImpl(
        config=config,
        inference_api=inference_api,
        files_api=files_api,
        models_api=models_api,
        sql_store=sql_store,
    )

    # Initialize the provider (should reconcile orphaned batches)
    await provider.initialize()

    # Verify create_table was called
    assert sql_store.create_table.called

    # Verify fetch_all was called for each non-terminal status
    fetch_calls = list(sql_store.fetch_all.call_args_list)
    assert len(fetch_calls) == 3

    # Verify update was called for each orphaned batch
    update_calls = sql_store.update.call_args_list
    assert len(update_calls) == 3

    # Verify the updates were correct
    for call in update_calls:
        kwargs = call.kwargs
        batch_id = kwargs["where"]["id"]
        data = kwargs["data"]
        batch_data = data["batch_data"]

        if batch_id == "batch_validating":
            assert data["status"] == "failed"
            assert batch_data["status"] == "failed"
            assert "failed_at" in batch_data
            assert "errors" in batch_data
            assert batch_data["errors"]["data"][0]["code"] == "provider_restart"
        elif batch_id == "batch_in_progress":
            assert data["status"] == "failed"
            assert batch_data["status"] == "failed"
            assert "failed_at" in batch_data
            assert "errors" in batch_data
            assert batch_data["errors"]["data"][0]["code"] == "provider_restart"
        elif batch_id == "batch_cancelling":
            assert data["status"] == "cancelled"
            assert batch_data["status"] == "cancelled"
            assert "cancelled_at" in batch_data


async def test_no_orphaned_batches_on_initialize():
    """Test that initialization works when no orphaned batches exist."""
    # Create mock dependencies
    config = ReferenceBatchesImplConfig(sqlstore=SqlStoreReference(backend="sql_default", table_name="batches"))
    inference_api = MagicMock()
    files_api = MagicMock()
    models_api = MagicMock()
    sql_store = AsyncMock()

    # Mock the create_table call
    sql_store.create_table = AsyncMock()

    # Mock fetch_all to return empty results
    sql_store.fetch_all = AsyncMock(return_value=PaginatedResponse(data=[], has_more=False))
    sql_store.update = AsyncMock()

    # Create the batches provider
    provider = ReferenceBatchesImpl(
        config=config,
        inference_api=inference_api,
        files_api=files_api,
        models_api=models_api,
        sql_store=sql_store,
    )

    # Initialize the provider
    await provider.initialize()

    # Verify create_table was called
    assert sql_store.create_table.called

    # Verify fetch_all was called for each non-terminal status
    assert sql_store.fetch_all.call_count == 3

    # Verify update was never called since there are no orphaned batches
    assert sql_store.update.call_count == 0
