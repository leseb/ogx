# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""Centralized schema definitions for all stable SQL tables.

This is the single source of truth for table schemas. Both service-level
create_table() calls and Alembic migrations reference these definitions.
"""

from collections.abc import Mapping

from ogx_api.internal.sqlstore import ColumnDefinition, ColumnType

SchemaType = Mapping[str, ColumnType | ColumnDefinition]

# --- Core service tables ---

PROMPTS_SCHEMA: SchemaType = {
    "id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
    "prompt_id": ColumnType.STRING,
    "version": ColumnType.INTEGER,
    "is_default": ColumnType.BOOLEAN,
    "created_at": ColumnType.INTEGER,
    "prompt_data": ColumnType.JSON,
}

CONVERSATIONS_SCHEMA: SchemaType = {
    "id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
    "created_at": ColumnType.INTEGER,
    "items": ColumnType.JSON,
    "metadata": ColumnType.JSON,
}

CONVERSATION_ITEMS_SCHEMA: SchemaType = {
    "id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
    "conversation_id": ColumnType.STRING,
    "created_at": ColumnType.INTEGER,
    "sort_order": ColumnType.INTEGER,
    "item_data": ColumnType.JSON,
}

CONNECTORS_SCHEMA: SchemaType = {
    "id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
    "connector_type": ColumnType.STRING,
    "url": ColumnType.STRING,
    "server_label": ColumnType.STRING,
    "server_name": ColumnType.STRING,
    "server_description": ColumnType.STRING,
    "connector_data": ColumnType.JSON,
}

# --- Provider tables ---

INFERENCE_STORE_SCHEMA: SchemaType = {
    "id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
    "created": ColumnType.INTEGER,
    "model": ColumnType.STRING,
    "choices": ColumnType.JSON,
    "input_messages": ColumnType.JSON,
}

RESPONSES_SCHEMA: SchemaType = {
    "id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
    "created_at": ColumnType.INTEGER,
    "response_object": ColumnType.JSON,
    "model": ColumnType.STRING,
    "previous_response_id": ColumnType.STRING,
    "input_storage_mode": ColumnType.STRING,
}

CONVERSATION_MESSAGES_SCHEMA: SchemaType = {
    "conversation_id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
    "messages": ColumnType.JSON,
}

BATCHES_SCHEMA: SchemaType = {
    "id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
    "created_at": ColumnType.INTEGER,
    "status": ColumnType.STRING,
    "batch_data": ColumnType.JSON,
}

INTERACTIONS_SCHEMA: SchemaType = {
    "id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
    "created_at": ColumnType.INTEGER,
    "model": ColumnType.STRING,
    "interaction_data": ColumnType.JSON,
}

# --- Files provider tables ---

FILES_LOCALFS_SCHEMA: SchemaType = {
    "id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
    "filename": ColumnType.STRING,
    "purpose": ColumnType.STRING,
    "bytes": ColumnType.INTEGER,
    "created_at": ColumnType.INTEGER,
    "expires_at": ColumnType.INTEGER,
    "file_path": ColumnType.STRING,
}

FILES_S3_SCHEMA: SchemaType = {
    "id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
    "filename": ColumnType.STRING,
    "purpose": ColumnType.STRING,
    "bytes": ColumnType.INTEGER,
    "created_at": ColumnType.INTEGER,
    "expires_at": ColumnType.INTEGER,
}

FILES_OPENAI_SCHEMA: SchemaType = {
    "id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
    "filename": ColumnType.STRING,
    "purpose": ColumnType.STRING,
    "bytes": ColumnType.INTEGER,
    "created_at": ColumnType.INTEGER,
    "expires_at": ColumnType.INTEGER,
}

# --- Vector store metadata tables ---

VECTOR_STORES_SCHEMA: SchemaType = {
    "id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
    "store_data": ColumnType.JSON,
}

VECTOR_STORE_FILES_SCHEMA: SchemaType = {
    "id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
    "store_id": ColumnType.STRING,
    "file_id": ColumnType.STRING,
    "file_data": ColumnType.JSON,
}

VECTOR_STORE_FILE_CONTENTS_SCHEMA: SchemaType = {
    "id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
    "store_id": ColumnType.STRING,
    "file_id": ColumnType.STRING,
    "chunk_index": ColumnType.INTEGER,
    "chunk_data": ColumnType.JSON,
}

VECTOR_STORE_FILE_BATCHES_SCHEMA: SchemaType = {
    "id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
    "store_id": ColumnType.STRING,
    "batch_data": ColumnType.JSON,
    "expires_at": ColumnType.INTEGER,
}

ALL_SCHEMAS: dict[str, SchemaType] = {
    "prompts": PROMPTS_SCHEMA,
    "openai_conversations": CONVERSATIONS_SCHEMA,
    "conversation_items": CONVERSATION_ITEMS_SCHEMA,
    "connectors": CONNECTORS_SCHEMA,
    "inference_store": INFERENCE_STORE_SCHEMA,
    "openai_responses": RESPONSES_SCHEMA,
    "conversation_messages": CONVERSATION_MESSAGES_SCHEMA,
    "batches": BATCHES_SCHEMA,
    "interactions": INTERACTIONS_SCHEMA,
    "files_localfs": FILES_LOCALFS_SCHEMA,
    "files_s3": FILES_S3_SCHEMA,
    "files_openai": FILES_OPENAI_SCHEMA,
    "vector_stores": VECTOR_STORES_SCHEMA,
    "vector_store_files": VECTOR_STORE_FILES_SCHEMA,
    "vector_store_file_contents": VECTOR_STORE_FILE_CONTENTS_SCHEMA,
    "vector_store_file_batches": VECTOR_STORE_FILE_BATCHES_SCHEMA,
}
