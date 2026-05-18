# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""Integration tests for Alembic migration upgrade procedure against PostgreSQL.

These tests exercise the full upgrade workflow: running `ogx db upgrade` against
a real PostgreSQL database, verifying backfill columns are added, custom table
names are respected, and the startup schema check works correctly.

Requires: ENABLE_POSTGRES_TESTS=1 and a running PostgreSQL instance.
Configure via POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD.
"""

import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from ogx.core.storage.migrations import EXPECTED_HEAD

pytestmark = pytest.mark.skipif(
    not os.environ.get("ENABLE_POSTGRES_TESTS"),
    reason="PostgreSQL tests require ENABLE_POSTGRES_TESTS environment variable",
)

_TEST_TABLE_PREFIX = "migration_test_"


def _pg_sync_url() -> str:
    """Build a synchronous PostgreSQL URL from environment variables."""
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "ogx")
    user = os.environ.get("POSTGRES_USER", "ogx")
    password = os.environ.get("POSTGRES_PASSWORD", "ogx")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def _alembic_cfg(db_url: str, **overrides: str) -> Config:
    """Create an Alembic Config pointing at the migrations dir."""
    migrations_dir = str(Path(__file__).parents[5] / "src" / "ogx" / "core" / "storage" / "migrations")
    cfg = Config()
    cfg.set_main_option("script_location", migrations_dir)
    cfg.set_main_option("sqlalchemy.url", db_url)
    for key, value in overrides.items():
        cfg.set_main_option(key, value)
    return cfg


def _get_current_revision(engine: sa.Engine) -> str | None:
    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        if "alembic_version" not in inspector.get_table_names():
            return None
        result = conn.execute(sa.text("SELECT version_num FROM alembic_version"))
        row = result.fetchone()
        return row[0] if row else None


@pytest.fixture
def pg_engine():
    """Create a PostgreSQL engine and clean up migration-related tables after test."""
    url = _pg_sync_url()
    engine = sa.create_engine(url)

    yield engine

    with engine.begin() as conn:
        inspector = sa.inspect(conn)
        existing = set(inspector.get_table_names())
        for table in existing:
            if table.startswith(_TEST_TABLE_PREFIX) or table == "alembic_version":
                conn.execute(sa.text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
    engine.dispose()


@pytest.fixture
def pg_url():
    return _pg_sync_url()


class TestUpgradeFreshDatabase:
    def test_stamps_alembic_version(self, pg_engine, pg_url):
        """Running upgrade on a database with no OGX tables stamps alembic_version."""
        with pg_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version CASCADE"))

        cfg = _alembic_cfg(pg_url)
        command.upgrade(cfg, "head")

        rev = _get_current_revision(pg_engine)
        assert rev == EXPECTED_HEAD

    def test_is_idempotent(self, pg_engine, pg_url):
        """Running upgrade twice succeeds without error."""
        with pg_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version CASCADE"))

        cfg = _alembic_cfg(pg_url)
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")

        rev = _get_current_revision(pg_engine)
        assert rev == EXPECTED_HEAD


class TestUpgradePreExistingTables:
    """Simulates in-place upgrade from a pre-Alembic OGX installation."""

    def test_adds_backfill_columns(self, pg_engine, pg_url):
        """Baseline migration adds missing columns to tables that existed before Alembic."""
        with pg_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version CASCADE"))
            conn.execute(sa.text("DROP TABLE IF EXISTS conversation_items CASCADE"))
            conn.execute(sa.text("DROP TABLE IF EXISTS openai_responses CASCADE"))
            conn.execute(
                sa.text("""
                CREATE TABLE conversation_items (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT,
                    created_at INTEGER,
                    item_data TEXT
                )
            """)
            )
            conn.execute(
                sa.text("""
                CREATE TABLE openai_responses (
                    id TEXT PRIMARY KEY,
                    created_at INTEGER,
                    response_object TEXT,
                    model TEXT
                )
            """)
            )

        cfg = _alembic_cfg(pg_url)
        command.upgrade(cfg, "head")

        with pg_engine.connect() as conn:
            inspector = sa.inspect(conn)

            ci_cols = {c["name"] for c in inspector.get_columns("conversation_items")}
            assert "sort_order" in ci_cols
            assert "access_attributes" in ci_cols
            assert "owner_principal" in ci_cols

            resp_cols = {c["name"] for c in inspector.get_columns("openai_responses")}
            assert "previous_response_id" in resp_cols
            assert "input_storage_mode" in resp_cols
            assert "access_attributes" in resp_cols
            assert "owner_principal" in resp_cols

        with pg_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS conversation_items CASCADE"))
            conn.execute(sa.text("DROP TABLE IF EXISTS openai_responses CASCADE"))

    def test_skips_nonexistent_tables(self, pg_engine, pg_url):
        """Migration does not fail when tables don't exist yet."""
        with pg_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version CASCADE"))

        cfg = _alembic_cfg(pg_url)
        command.upgrade(cfg, "head")

        with pg_engine.connect() as conn:
            inspector = sa.inspect(conn)
            tables = set(inspector.get_table_names())
            assert "alembic_version" in tables
            assert "prompts" not in tables


class TestCustomTableNames:
    """Tests that configurable table names are respected by migrations."""

    def test_custom_responses_table_gets_backfills(self, pg_engine, pg_url):
        """Backfill columns are added to the custom-named responses table."""
        custom_table = f"{_TEST_TABLE_PREFIX}responses"
        with pg_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version CASCADE"))
            conn.execute(sa.text(f'DROP TABLE IF EXISTS "{custom_table}" CASCADE'))
            conn.execute(
                sa.text(f"""
                CREATE TABLE "{custom_table}" (
                    id TEXT PRIMARY KEY,
                    created_at INTEGER,
                    response_object TEXT,
                    model TEXT
                )
            """)
            )

        cfg = _alembic_cfg(pg_url, x_responses_table=custom_table)
        command.upgrade(cfg, "head")

        with pg_engine.connect() as conn:
            inspector = sa.inspect(conn)
            cols = {c["name"] for c in inspector.get_columns(custom_table)}
            assert "previous_response_id" in cols
            assert "input_storage_mode" in cols
            assert "access_attributes" in cols
            assert "owner_principal" in cols

    def test_default_table_untouched_when_custom_name_set(self, pg_engine, pg_url):
        """When custom name is set, default-named table is not modified."""
        custom_table = f"{_TEST_TABLE_PREFIX}my_responses"
        with pg_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version CASCADE"))
            conn.execute(sa.text("DROP TABLE IF EXISTS openai_responses CASCADE"))
            conn.execute(sa.text(f'DROP TABLE IF EXISTS "{custom_table}" CASCADE'))
            conn.execute(
                sa.text("""
                CREATE TABLE openai_responses (
                    id TEXT PRIMARY KEY,
                    model TEXT
                )
            """)
            )
            conn.execute(
                sa.text(f"""
                CREATE TABLE "{custom_table}" (
                    id TEXT PRIMARY KEY,
                    model TEXT
                )
            """)
            )

        cfg = _alembic_cfg(pg_url, x_responses_table=custom_table)
        command.upgrade(cfg, "head")

        with pg_engine.connect() as conn:
            inspector = sa.inspect(conn)
            default_cols = {c["name"] for c in inspector.get_columns("openai_responses")}
            assert "previous_response_id" not in default_cols

            custom_cols = {c["name"] for c in inspector.get_columns(custom_table)}
            assert "previous_response_id" in custom_cols
            assert "access_attributes" in custom_cols

        with pg_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS openai_responses CASCADE"))


class TestStartupSchemaCheck:
    """Tests the startup version check logic against a real PostgreSQL database."""

    @pytest.fixture
    def pg_config(self):
        from ogx.core.storage.datatypes import PostgresSqlStoreConfig

        return PostgresSqlStoreConfig(
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            db=os.environ.get("POSTGRES_DB", "ogx"),
            user=os.environ.get("POSTGRES_USER", "ogx"),
            password=os.environ.get("POSTGRES_PASSWORD", "ogx"),
        )

    @pytest.fixture
    def stack_config(self, pg_config):
        """Minimal StackConfig with a PostgreSQL backend for testing the startup check."""
        from unittest.mock import MagicMock

        from ogx.core.storage.datatypes import (
            KVStoreReference,
            ServerStoresConfig,
            SqlStoreReference,
            StorageConfig,
        )

        config = MagicMock()
        config.storage = StorageConfig(
            backends={"sql_default": pg_config},
            stores=ServerStoresConfig(
                metadata=KVStoreReference(backend="kv_default", namespace="registry"),
                inference=None,
                conversations=SqlStoreReference(backend="sql_default", table_name="openai_conversations"),
                responses=None,
                prompts=SqlStoreReference(backend="sql_default", table_name="prompts"),
                connectors=SqlStoreReference(backend="sql_default", table_name="connectors"),
            ),
        )
        return config

    async def test_passes_after_upgrade(self, pg_engine, pg_url, stack_config):
        """Startup check passes when schema is at expected revision."""
        with pg_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version CASCADE"))

        cfg = _alembic_cfg(pg_url)
        command.upgrade(cfg, "head")

        from ogx.core.server.server import _check_postgres_schema_versions

        await _check_postgres_schema_versions(stack_config)

    async def test_fails_on_pre_migration_database(self, pg_engine, stack_config):
        """Startup check refuses a database with tables but no alembic_version."""
        with pg_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version CASCADE"))
            conn.execute(sa.text("DROP TABLE IF EXISTS prompts CASCADE"))
            conn.execute(sa.text("CREATE TABLE prompts (id TEXT PRIMARY KEY)"))

        from ogx.core.server.server import _check_postgres_schema_versions

        with pytest.raises(SystemExit):
            await _check_postgres_schema_versions(stack_config)

        with pg_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS prompts CASCADE"))

    async def test_passes_on_fresh_database(self, pg_engine, stack_config):
        """Startup check allows a completely fresh database (no tables at all)."""
        with pg_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version CASCADE"))
            conn.execute(sa.text("DROP TABLE IF EXISTS prompts CASCADE"))
            conn.execute(sa.text("DROP TABLE IF EXISTS openai_conversations CASCADE"))
            conn.execute(sa.text("DROP TABLE IF EXISTS connectors CASCADE"))

        from ogx.core.server.server import _check_postgres_schema_versions

        await _check_postgres_schema_versions(stack_config)

    async def test_fails_on_stale_revision(self, pg_engine, pg_url, stack_config):
        """Startup check refuses when alembic_version is behind EXPECTED_HEAD."""
        with pg_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version CASCADE"))
            conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
            conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('000')"))

        from ogx.core.server.server import _check_postgres_schema_versions

        with pytest.raises(SystemExit):
            await _check_postgres_schema_versions(stack_config)

    async def test_warns_on_ahead_revision(self, pg_engine, stack_config):
        """Startup check warns but does not exit when schema is ahead of binary."""
        with pg_engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version CASCADE"))
            conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
            conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('999')"))

        from ogx.core.server.server import _check_postgres_schema_versions

        await _check_postgres_schema_versions(stack_config)
