# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""Alembic environment configuration.

Configured programmatically — no alembic.ini needed.
Uses the database URL from the OGX server config.
"""

from alembic import context
from sqlalchemy import create_engine, pool


def get_url() -> str:
    url = context.config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("sqlalchemy.url must be set in Alembic config")
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emit SQL without connecting."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _get_x_args() -> dict[str, str]:
    """Extract x_ prefixed args from config as migration parameters."""
    config = context.config
    result: dict[str, str] = {}
    if config is not None:
        for key in ("x_responses_table", "x_inference_table"):
            val = config.get_main_option(key)
            if val:
                result[key.removeprefix("x_")] = val
    return result


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connect and execute."""
    url = get_url()
    connectable = create_engine(url, poolclass=pool.NullPool)
    x_args = _get_x_args()
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations(**x_args)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
