# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""Tests for centralized schema definitions."""

from ogx.core.storage.schema import (
    ALL_SCHEMAS,
    CONNECTORS_SCHEMA,
    CONVERSATION_ITEMS_SCHEMA,
    CONVERSATIONS_SCHEMA,
    FILES_LOCALFS_SCHEMA,
    FILES_OPENAI_SCHEMA,
    FILES_S3_SCHEMA,
    RESPONSES_SCHEMA,
)
from ogx_api.internal.sqlstore import ColumnDefinition, ColumnType


def test_all_schemas_has_16_entries():
    assert len(ALL_SCHEMAS) == 16


def test_every_schema_has_a_primary_key():
    for name, schema in ALL_SCHEMAS.items():
        pk_found = False
        for _col_name, col_def in schema.items():
            if isinstance(col_def, ColumnDefinition) and col_def.primary_key:
                pk_found = True
                break
        assert pk_found, f"Schema '{name}' has no primary key column"


def test_every_schema_uses_valid_column_types():
    valid_types = set(ColumnType)
    for name, schema in ALL_SCHEMAS.items():
        for col_name, col_def in schema.items():
            if isinstance(col_def, ColumnType):
                assert col_def in valid_types, f"Schema '{name}' column '{col_name}' has invalid type"
            elif isinstance(col_def, ColumnDefinition):
                assert col_def.type in valid_types, f"Schema '{name}' column '{col_name}' has invalid type"


def test_prompts_schema_columns():
    assert "id" in CONNECTORS_SCHEMA
    assert "prompt_id" not in CONNECTORS_SCHEMA
    assert "prompt_data" not in CONNECTORS_SCHEMA


def test_conversations_schema_includes_deprecated_items():
    assert "items" in CONVERSATIONS_SCHEMA


def test_conversation_items_schema_includes_sort_order():
    assert "sort_order" in CONVERSATION_ITEMS_SCHEMA


def test_responses_schema_includes_backfill_columns():
    assert "previous_response_id" in RESPONSES_SCHEMA
    assert "input_storage_mode" in RESPONSES_SCHEMA


def test_files_localfs_has_file_path():
    assert "file_path" in FILES_LOCALFS_SCHEMA


def test_files_s3_has_no_file_path():
    assert "file_path" not in FILES_S3_SCHEMA


def test_files_openai_has_no_file_path():
    assert "file_path" not in FILES_OPENAI_SCHEMA
