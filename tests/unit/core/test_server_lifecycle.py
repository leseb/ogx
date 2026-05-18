# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""Tests for the two-phase server startup lifecycle.

Phase 1 (prepare): Creates provider impls and registers SQL table metadata
in a temporary event loop. No SQL data operations, no engine creation.

Phase 2 (start): Runs data operations (register_resources, register_connectors)
in uvicorn's event loop via the lifespan handler.
"""

import asyncio
import logging  # allow-direct-logging

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


def test_prepare_does_not_create_engine(tmp_path):
    """Simulates prepare() phase: table registration does not trigger engine creation."""
    db_path = str(tmp_path / "test.db")
    store = SqlAlchemySqlStoreImpl(SqliteSqlStoreConfig(db_path=db_path))

    async def prepare_phase():
        await store.create_table(
            "test_table",
            {"id": ColumnDefinition(type=ColumnType.STRING, primary_key=True), "value": ColumnType.STRING},
        )

    asyncio.run(prepare_phase())
    assert store._engine is None, "create_table should not trigger engine creation"
    assert "test_table" in store.metadata.tables


def test_two_phase_lifecycle(tmp_path):
    """Full two-phase lifecycle: prepare (temp loop) -> reset -> start (new loop)."""
    db_path = str(tmp_path / "test.db")
    store = SqlAlchemySqlStoreImpl(SqliteSqlStoreConfig(db_path=db_path))

    # Phase 1: prepare — register tables, no engine
    async def prepare_phase():
        await store.create_table(
            "items",
            {"id": ColumnDefinition(type=ColumnType.STRING, primary_key=True), "value": ColumnType.STRING},
        )

    asyncio.run(prepare_phase())
    assert store._engine is None

    store.reset_engine()

    # Phase 2: start — data operations create engine in the correct loop
    async def start_phase():
        await store.insert("items", {"id": "row1", "value": "from_start"})
        result = await store.fetch_all("items")
        return result

    result = asyncio.run(start_phase())
    assert store._engine is not None
    assert len(result.data) == 1
    assert result.data[0]["id"] == "row1"


def _cleanup(store: SqlAlchemySqlStoreImpl) -> None:
    if store._engine is not None:
        try:
            asyncio.run(store.shutdown())
        except Exception:
            store._engine = None
