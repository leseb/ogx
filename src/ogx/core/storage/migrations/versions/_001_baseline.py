# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""Baseline migration: stamp schema version and ensure backfill columns.

Revision ID: 001
Revises: None
Create Date: 2026-05-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_BACKFILL_COLUMNS: list[tuple[str, str, sa.types.TypeEngine]] = [
    ("conversation_items", "sort_order", sa.Integer()),
    ("openai_responses", "previous_response_id", sa.String()),
    ("openai_responses", "input_storage_mode", sa.String()),
]

_ACCESS_CONTROL_COLUMNS: list[tuple[str, sa.types.TypeEngine]] = [
    ("access_attributes", sa.JSON()),
    ("owner_principal", sa.String()),
]

_ALL_TABLES = [
    "prompts",
    "openai_conversations",
    "conversation_items",
    "connectors",
    "inference_store",
    "openai_responses",
    "conversation_messages",
    "batches",
    "interactions",
    "openai_files",
    "vector_stores",
    "vector_store_files",
    "vector_store_file_contents",
    "vector_store_file_batches",
]


def upgrade(responses_table: str = "openai_responses", inference_table: str = "inference_store", **kwargs) -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = set(inspector.get_table_names())

    all_tables = list(_ALL_TABLES)
    if "openai_responses" in all_tables:
        all_tables[all_tables.index("openai_responses")] = responses_table
    if "inference_store" in all_tables:
        all_tables[all_tables.index("inference_store")] = inference_table

    backfill_columns = [
        (col_table if col_table != "openai_responses" else responses_table, col_name, col_type)
        for col_table, col_name, col_type in _BACKFILL_COLUMNS
    ]

    for table_name in all_tables:
        if table_name not in existing_tables:
            continue

        existing_columns = {c["name"] for c in inspector.get_columns(table_name)}

        for col_table, col_name, col_type in backfill_columns:
            if col_table == table_name and col_name not in existing_columns:
                op.add_column(table_name, sa.Column(col_name, col_type, nullable=True))

        for col_name, col_type in _ACCESS_CONTROL_COLUMNS:
            if col_name not in existing_columns:
                op.add_column(table_name, sa.Column(col_name, col_type, nullable=True))


def downgrade() -> None:
    pass
