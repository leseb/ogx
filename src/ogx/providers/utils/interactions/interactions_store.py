# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

from __future__ import annotations

from typing import Any

from ogx.core.datatypes import AccessRule
from ogx.core.storage.datatypes import SqlStoreReference
from ogx.core.storage.sqlstore.authorized_sqlstore import authorized_sqlstore
from ogx.log import get_logger
from ogx_api.internal.sqlstore import ColumnDefinition, ColumnType

logger = get_logger(name=__name__, category="interactions")


class InteractionsStore:
    """Persistent store for Google Interactions API state with SQL-backed storage.

    Stores completed interaction data (messages + output) so that subsequent
    requests can chain via ``previous_interaction_id``.
    """

    def __init__(self, reference: SqlStoreReference, policy: list[AccessRule]):
        self.reference = reference
        self.policy = policy

    async def initialize(self) -> None:
        """Create the interactions table if it does not exist."""
        self.sql_store = await authorized_sqlstore(self.reference, self.policy)
        await self.sql_store.create_table(
            self.reference.table_name,
            {
                "id": ColumnDefinition(type=ColumnType.STRING, primary_key=True),
                "created_at": ColumnType.INTEGER,
                "model": ColumnType.STRING,
                "interaction_data": ColumnType.JSON,
            },
        )

    async def shutdown(self) -> None:
        return

    async def store_interaction(
        self,
        interaction_id: str,
        created_at: int,
        model: str,
        messages: list[dict[str, Any]],
        output_text: str,
        output_message: dict[str, Any] | None = None,
    ) -> None:
        """Persist a completed interaction for future chaining.

        ``output_message`` is the full OpenAI-format assistant message dict
        (including ``tool_calls`` when present).  It is stored alongside the
        legacy ``output_text`` field so that ``get_interaction`` callers can
        reconstruct structured assistant turns for conversation chaining.
        """
        interaction_data: dict[str, Any] = {
            "messages": messages,
            "output_text": output_text,
        }
        if output_message is not None:
            interaction_data["output_message"] = output_message

        await self.sql_store.insert(
            self.reference.table_name,
            {
                "id": interaction_id,
                "created_at": created_at,
                "model": model,
                "interaction_data": interaction_data,
            },
        )

    async def get_interaction(self, interaction_id: str) -> dict[str, Any] | None:
        """Retrieve a stored interaction by ID.

        Returns the ``interaction_data`` dict which contains:

        - ``messages``: the input messages for this interaction
        - ``output_text``: plain text output (always present)
        - ``output_message``: full OpenAI-format assistant message dict
          including ``tool_calls`` (present for interactions stored after the
          structured output fix; absent for legacy rows)

        Returns ``None`` if the interaction is not found.
        """
        row = await self.sql_store.fetch_one(
            self.reference.table_name,
            where={"id": interaction_id},
        )
        if not row:
            return None
        data: dict[str, Any] = row["interaction_data"]
        return data
