# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""Unit tests for migration infrastructure (import checks only)."""

from ogx.core.storage.migrations import EXPECTED_HEAD


def test_expected_head_is_set():
    assert EXPECTED_HEAD == "001"


def test_baseline_migration_importable():
    from ogx.core.storage.migrations.versions._001_baseline import down_revision, revision

    assert revision == "001"
    assert down_revision is None


def test_history_contains_baseline():
    """Migration script directory contains the baseline revision."""
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    migrations_dir = str(Path(__file__).parents[3] / "src" / "ogx" / "core" / "storage" / "migrations")
    cfg = Config()
    cfg.set_main_option("script_location", migrations_dir)
    script_dir = ScriptDirectory.from_config(cfg)
    revisions = list(script_dir.walk_revisions())

    assert len(revisions) >= 1
    baseline = revisions[-1]
    assert baseline.revision == "001"
    assert baseline.down_revision is None
