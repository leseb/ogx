# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""Tests for migration infrastructure.

Tests the full upgrade procedure: running Alembic against a real database,
verifying schema changes, and testing the startup version check logic.
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from ogx.core.storage.migrations import EXPECTED_HEAD


def _alembic_cfg(db_url: str) -> Config:
    """Create an Alembic Config pointing at the migrations dir with the given DB URL."""
    migrations_dir = str(Path(__file__).parents[3] / "src" / "ogx" / "core" / "storage" / "migrations")
    cfg = Config()
    cfg.set_main_option("script_location", migrations_dir)
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _get_current_revision(engine: sa.Engine) -> str | None:
    """Read the current Alembic revision from alembic_version table."""
    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        if "alembic_version" not in inspector.get_table_names():
            return None
        result = conn.execute(sa.text("SELECT version_num FROM alembic_version"))
        row = result.fetchone()
        return row[0] if row else None


# --- Basic import tests ---


def test_expected_head_is_set():
    assert EXPECTED_HEAD == "001"


def test_baseline_migration_importable():
    from ogx.core.storage.migrations.versions._001_baseline import down_revision, revision

    assert revision == "001"
    assert down_revision is None


# --- Upgrade against fresh database ---


def test_upgrade_fresh_database(tmp_path):
    """Running upgrade on an empty database stamps alembic_version."""
    db_path = tmp_path / "fresh.db"
    db_url = f"sqlite:///{db_path}"
    cfg = _alembic_cfg(db_url)

    command.upgrade(cfg, "head")

    engine = sa.create_engine(db_url)
    rev = _get_current_revision(engine)
    assert rev == "001"
    engine.dispose()


def test_upgrade_is_idempotent(tmp_path):
    """Running upgrade twice succeeds without error."""
    db_path = tmp_path / "idempotent.db"
    db_url = f"sqlite:///{db_path}"
    cfg = _alembic_cfg(db_url)

    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")

    engine = sa.create_engine(db_url)
    rev = _get_current_revision(engine)
    assert rev == "001"
    engine.dispose()


# --- Upgrade with pre-existing tables (simulates in-place upgrade) ---


def test_upgrade_adds_backfill_columns_to_existing_tables(tmp_path):
    """Baseline migration adds missing columns to tables that existed before Alembic."""
    db_path = tmp_path / "preexisting.db"
    db_url = f"sqlite:///{db_path}"
    engine = sa.create_engine(db_url)

    with engine.begin() as conn:
        conn.execute(sa.text("""
            CREATE TABLE conversation_items (
                id TEXT PRIMARY KEY,
                conversation_id TEXT,
                created_at INTEGER,
                item_data TEXT
            )
        """))
        conn.execute(sa.text("""
            CREATE TABLE openai_responses (
                id TEXT PRIMARY KEY,
                created_at INTEGER,
                response_object TEXT,
                model TEXT
            )
        """))

    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        cols_before = {c["name"] for c in inspector.get_columns("conversation_items")}
        assert "sort_order" not in cols_before
        resp_cols_before = {c["name"] for c in inspector.get_columns("openai_responses")}
        assert "previous_response_id" not in resp_cols_before
        assert "input_storage_mode" not in resp_cols_before

    cfg = _alembic_cfg(db_url)
    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        cols_after = {c["name"] for c in inspector.get_columns("conversation_items")}
        assert "sort_order" in cols_after
        assert "access_attributes" in cols_after
        assert "owner_principal" in cols_after

        resp_cols_after = {c["name"] for c in inspector.get_columns("openai_responses")}
        assert "previous_response_id" in resp_cols_after
        assert "input_storage_mode" in resp_cols_after
        assert "access_attributes" in resp_cols_after
        assert "owner_principal" in resp_cols_after

    engine.dispose()


def test_upgrade_skips_nonexistent_tables(tmp_path):
    """Baseline migration does not fail when tables don't exist yet."""
    db_path = tmp_path / "empty.db"
    db_url = f"sqlite:///{db_path}"
    cfg = _alembic_cfg(db_url)

    command.upgrade(cfg, "head")

    engine = sa.create_engine(db_url)
    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        tables = inspector.get_table_names()
        assert "alembic_version" in tables
        assert "prompts" not in tables
    engine.dispose()


def test_upgrade_with_custom_responses_table_name(tmp_path):
    """Baseline migration respects configurable table name for responses."""
    db_path = tmp_path / "custom_name.db"
    db_url = f"sqlite:///{db_path}"
    engine = sa.create_engine(db_url)

    with engine.begin() as conn:
        conn.execute(sa.text("""
            CREATE TABLE responses (
                id TEXT PRIMARY KEY,
                created_at INTEGER,
                response_object TEXT,
                model TEXT
            )
        """))

    cfg = _alembic_cfg(db_url)
    cfg.set_main_option("x_responses_table", "responses")
    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        cols = {c["name"] for c in inspector.get_columns("responses")}
        assert "previous_response_id" in cols
        assert "input_storage_mode" in cols
        assert "access_attributes" in cols
    engine.dispose()


def test_upgrade_does_not_touch_default_table_when_custom_name_set(tmp_path):
    """When custom table name is set, default-named table is not modified."""
    db_path = tmp_path / "custom_only.db"
    db_url = f"sqlite:///{db_path}"
    engine = sa.create_engine(db_url)

    with engine.begin() as conn:
        conn.execute(sa.text("""
            CREATE TABLE openai_responses (
                id TEXT PRIMARY KEY,
                model TEXT
            )
        """))
        conn.execute(sa.text("""
            CREATE TABLE my_responses (
                id TEXT PRIMARY KEY,
                model TEXT
            )
        """))

    cfg = _alembic_cfg(db_url)
    cfg.set_main_option("x_responses_table", "my_responses")
    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        default_cols = {c["name"] for c in inspector.get_columns("openai_responses")}
        assert "previous_response_id" not in default_cols

        custom_cols = {c["name"] for c in inspector.get_columns("my_responses")}
        assert "access_attributes" in custom_cols
    engine.dispose()


# --- alembic current / history commands ---


def test_current_shows_head_after_upgrade(tmp_path):
    """After upgrade, alembic_version contains the head revision."""
    db_path = tmp_path / "current.db"
    db_url = f"sqlite:///{db_path}"
    cfg = _alembic_cfg(db_url)

    command.upgrade(cfg, "head")

    engine = sa.create_engine(db_url)
    rev = _get_current_revision(engine)
    assert rev == EXPECTED_HEAD
    engine.dispose()


def test_history_contains_baseline():
    """Migration script directory contains the baseline revision."""
    from alembic.script import ScriptDirectory

    db_url = "sqlite://"
    cfg = _alembic_cfg(db_url)
    script_dir = ScriptDirectory.from_config(cfg)
    revisions = list(script_dir.walk_revisions())

    assert len(revisions) >= 1
    baseline = revisions[-1]
    assert baseline.revision == "001"
    assert baseline.down_revision is None
