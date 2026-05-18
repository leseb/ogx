# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""Tests for migration infrastructure."""

from ogx.core.storage.migrations import EXPECTED_HEAD


def test_expected_head_is_set():
    assert EXPECTED_HEAD == "001"


def test_baseline_migration_importable():
    from ogx.core.storage.migrations.versions._001_baseline import revision, down_revision

    assert revision == "001"
    assert down_revision is None
