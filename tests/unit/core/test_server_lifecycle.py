# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""Tests that the server startup lifecycle correctly resets SQL engines.

Verifies that after Stack.initialize() runs in a temporary event loop,
SQL engines are reset so they can be recreated in uvicorn's request loop.
"""

import asyncio
import logging

from ogx.core.storage.datatypes import SqliteSqlStoreConfig
from ogx.core.storage.sqlstore.sqlalchemy_sqlstore import SqlAlchemySqlStoreImpl
from ogx.core.storage.sqlstore.sqlstore import (
    _SQLSTORE_INSTANCES,
    register_sqlstore_backends,
    reset_sqlstore_engines,
    set_sqlstore_init_phase,
)
from ogx_api.internal.sqlstore import ColumnDefinition, ColumnType


def test_reset_sqlstore_engines_clears_all_instances(tmp_path):
    """reset_sqlstore_engines() resets engine on every cached instance."""
    db_path = str(tmp_path / "test.db")
    register_sqlstore_backends({"sql_default": SqliteSqlStoreConfig(db_path=db_path)})

    async def create_engine():
        from ogx.core.storage.sqlstore.sqlstore import _sqlstore_impl

        store = await _sqlstore_impl(
            type("Ref", (), {"backend": "sql_default", "table_name": "t"})()  # type: ignore[arg-type]
        )
        await store.create_table("t", {"id": ColumnDefinition(type=ColumnType.STRING, primary_key=True)})
        await store.insert("t", {"id": "1"})
        return store

    store = asyncio.run(create_engine())
    assert store._engine is not None

    reset_sqlstore_engines()

    for instance in _SQLSTORE_INSTANCES.values():
        assert instance._engine is None


def test_init_phase_warning_on_ensure_engine(tmp_path, caplog):
    """_ensure_engine() logs a warning when called during init phase."""
    db_path = str(tmp_path / "test.db")
    store = SqlAlchemySqlStoreImpl(SqliteSqlStoreConfig(db_path=db_path))
    store._set_init_phase(True)

    async def trigger():
        await store.create_table("t", {"id": ColumnDefinition(type=ColumnType.STRING, primary_key=True)})
        with caplog.at_level(logging.WARNING):
            await store.insert("t", {"id": "1"})

    asyncio.run(trigger())
    assert any("SQL engine created during init phase" in r.message for r in caplog.records)
    _cleanup(store)


def test_no_init_phase_warning_outside_init(tmp_path, caplog):
    """_ensure_engine() does not warn when init phase is inactive."""
    db_path = str(tmp_path / "test.db")
    store = SqlAlchemySqlStoreImpl(SqliteSqlStoreConfig(db_path=db_path))

    async def trigger():
        await store.create_table("t", {"id": ColumnDefinition(type=ColumnType.STRING, primary_key=True)})
        with caplog.at_level(logging.WARNING):
            await store.insert("t", {"id": "1"})

    asyncio.run(trigger())
    assert not any("SQL engine created during init phase" in r.message for r in caplog.records)
    _cleanup(store)


def test_set_sqlstore_init_phase_propagates(tmp_path):
    """set_sqlstore_init_phase() sets the flag on all cached instances."""
    db_path = str(tmp_path / "test.db")
    register_sqlstore_backends({"sql_default": SqliteSqlStoreConfig(db_path=db_path)})

    async def create():
        from ogx.core.storage.sqlstore.sqlstore import _sqlstore_impl

        return await _sqlstore_impl(
            type("Ref", (), {"backend": "sql_default", "table_name": "t"})()  # type: ignore[arg-type]
        )

    store = asyncio.run(create())

    set_sqlstore_init_phase(True)
    assert store._init_phase is True

    set_sqlstore_init_phase(False)
    assert store._init_phase is False


def test_server_init_lifecycle_engines_reset_after_init(tmp_path):
    """Simulates the full server init lifecycle: init in temp loop -> reset -> use in new loop."""
    db_path = str(tmp_path / "test.db")
    register_sqlstore_backends({"sql_default": SqliteSqlStoreConfig(db_path=db_path)})

    async def init_in_temp_loop():
        from ogx.core.storage.sqlstore.sqlstore import _sqlstore_impl

        set_sqlstore_init_phase(True)

        store = await _sqlstore_impl(
            type("Ref", (), {"backend": "sql_default", "table_name": "t"})()  # type: ignore[arg-type]
        )
        await store.create_table(
            "lifecycle_test",
            {"id": ColumnDefinition(type=ColumnType.STRING, primary_key=True), "value": ColumnType.STRING},
        )
        await store.insert("lifecycle_test", {"id": "init_row", "value": "from_init"})

        set_sqlstore_init_phase(False)
        return store

    store = asyncio.run(init_in_temp_loop())
    assert store._engine is not None

    reset_sqlstore_engines()
    assert store._engine is None

    async def use_in_request_loop():
        await store.insert("lifecycle_test", {"id": "request_row", "value": "from_request"})
        result = await store.fetch_all("lifecycle_test")
        return result

    result = asyncio.run(use_in_request_loop())
    assert len(result.data) == 2
    ids = {row["id"] for row in result.data}
    assert ids == {"init_row", "request_row"}


def _cleanup(store: SqlAlchemySqlStoreImpl) -> None:
    if store._engine is not None:
        try:
            asyncio.run(store.shutdown())
        except Exception:
            store._engine = None
