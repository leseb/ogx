# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

import os

import asyncpg
import pytest

# Import fixtures from common module to make them available in this test directory
from tests.integration.fixtures.common import (  # noqa: F401
    openai_client,
    require_server,
)


def pytest_configure(config):
    os.environ["OGX_TEST_LOG_STDERR"] = "0"


@pytest.fixture(scope="session")
def pg_conn():
    """Direct asyncpg connection to the test PostgreSQL database.

    Returns a synchronous wrapper so non-async tests can query the DB.
    """
    import asyncio

    async def _connect():
        return await asyncpg.connect(
            host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            database=os.environ.get("POSTGRES_DB", "ogx"),
            user=os.environ.get("POSTGRES_USER", "ogx"),
            password=os.environ.get("POSTGRES_PASSWORD", "ogx"),
        )

    conn = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_connect())
    yield conn
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(conn.close())


@pytest.fixture
def db(pg_conn):
    """Helper that wraps pg_conn with a sync query method."""
    import asyncio

    class SyncDB:
        def __init__(self, conn):
            self._conn = conn
            self._loop = asyncio.new_event_loop()

        def fetchrow(self, query, *args):
            return self._loop.run_until_complete(self._conn.fetchrow(query, *args))

        def fetch(self, query, *args):
            return self._loop.run_until_complete(self._conn.fetch(query, *args))

    return SyncDB(pg_conn)
