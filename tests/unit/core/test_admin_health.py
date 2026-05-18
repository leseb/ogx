# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

from types import SimpleNamespace

from ogx.core.admin import AdminImpl
from ogx.core.storage.datatypes import InferenceStoreReference, SqliteSqlStoreConfig
from ogx.core.storage.sqlstore.sqlstore import register_sqlstore_backends
from ogx.providers.utils.inference.inference_store import InferenceStore
from ogx_api import (
    Api,
    HealthStatus,
    OpenAIChatCompletion,
    OpenAIChatCompletionResponseMessage,
    OpenAIChoice,
    OpenAIUserMessageParam,
)


def _make_completion(completion_id: str) -> OpenAIChatCompletion:
    return OpenAIChatCompletion(
        id=completion_id,
        created=1000,
        model="test-model",
        object="chat.completion",
        choices=[
            OpenAIChoice(
                index=0,
                message=OpenAIChatCompletionResponseMessage(role="assistant", content="ok"),
                finish_reason="stop",
            )
        ],
    )


async def test_admin_health_reports_inference_store_write_failures(tmp_path):
    """Admin health returns ERROR when async inference-store writes fail."""
    db_path = str(tmp_path / "test.db")
    register_sqlstore_backends({"sql_default": SqliteSqlStoreConfig(db_path=db_path)})

    store = InferenceStore(
        InferenceStoreReference(backend="sql_default", table_name="inference_store"),
        policy=[],
    )
    await store.initialize()

    try:
        # Exercise worker-path failures where _write_error_count is incremented.
        store.enable_write_queue = True
        store._num_writers = 1
        store._queue = None
        store._worker_tasks = []

        async def failing_write(*_args, **_kwargs):
            raise RuntimeError("simulated write failure")

        store._write_chat_completion = failing_write

        await store.store_chat_completion(
            _make_completion("cmpl-failure"),
            [OpenAIUserMessageParam(role="user", content="hi")],
        )
        await store.flush()
        assert store._write_error_count == 1

        admin = AdminImpl.__new__(AdminImpl)
        admin.deps = {Api.inference: SimpleNamespace(store=store)}

        health = await AdminImpl.health(admin)
        assert health.status == HealthStatus.ERROR
    finally:
        await store.shutdown()
