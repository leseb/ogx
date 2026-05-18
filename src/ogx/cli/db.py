# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

import argparse
import os
import sys
from pathlib import Path

from ogx.cli.subcommand import Subcommand
from ogx.log import get_logger

logger = get_logger(name=__name__, category="cli")


class Db(Subcommand):
    """CLI subcommand group for database management."""

    def __init__(self, subparsers: argparse._SubParsersAction) -> None:
        super().__init__()
        self.parser = subparsers.add_parser(
            "db",
            prog="ogx db",
            description="Database schema management commands for PostgreSQL backends.",
            formatter_class=argparse.RawTextHelpFormatter,
        )
        db_subparsers = self.parser.add_subparsers(title="db commands")

        upgrade_parser = db_subparsers.add_parser(
            "upgrade",
            prog="ogx db upgrade",
            description="Apply pending schema migrations to all PostgreSQL backends.",
        )
        upgrade_parser.add_argument(
            "config",
            type=str,
            nargs="?",
            metavar="config",
            help="Path to OGX config file. Falls back to OGX_CONFIG env var.",
        )
        upgrade_parser.set_defaults(func=self._run_upgrade_cmd)

        current_parser = db_subparsers.add_parser(
            "current",
            prog="ogx db current",
            description="Show current schema revision for all PostgreSQL backends.",
        )
        current_parser.add_argument(
            "config",
            type=str,
            nargs="?",
            metavar="config",
            help="Path to OGX config file. Falls back to OGX_CONFIG env var.",
        )
        current_parser.set_defaults(func=self._run_current_cmd)

        history_parser = db_subparsers.add_parser(
            "history",
            prog="ogx db history",
            description="Show migration revision history.",
        )
        history_parser.set_defaults(func=self._run_history_cmd)

        self.parser.set_defaults(func=lambda args: self.parser.print_help())

    def _resolve_config(self, args: argparse.Namespace) -> Path:
        config_path = getattr(args, "config", None) or os.environ.get("OGX_CONFIG")
        if not config_path:
            logger.error("No config file specified. Pass a config path or set OGX_CONFIG.")
            sys.exit(1)
        from ogx.core.utils.config_resolution import resolve_config_or_distro

        return resolve_config_or_distro(config_path)

    def _get_postgres_urls(self, config_path: Path) -> list[tuple[str, str]]:
        """Extract all unique PostgreSQL backend DSNs from config.

        Returns list of (backend_name, dsn) tuples.
        """
        import yaml

        from ogx.core.configure import parse_and_maybe_upgrade_config

        config_dict = yaml.safe_load(config_path.read_text())
        config = parse_and_maybe_upgrade_config(config_dict)

        from ogx.core.storage.datatypes import PostgresSqlStoreConfig

        results: list[tuple[str, str]] = []
        seen_dsns: set[str] = set()
        for name, backend in config.storage.backends.items():
            if isinstance(backend, PostgresSqlStoreConfig):
                dsn = backend.engine_str
                if dsn not in seen_dsns:
                    seen_dsns.add(dsn)
                    results.append((name, dsn))
        return results

    def _get_table_name_overrides(self, config_path: Path) -> dict[str, str]:
        """Extract configurable table names from config for migration parameterization."""
        import yaml

        from ogx.core.configure import parse_and_maybe_upgrade_config

        config_dict = yaml.safe_load(config_path.read_text())
        config = parse_and_maybe_upgrade_config(config_dict)

        overrides: dict[str, str] = {}
        stores = config.storage.stores
        if stores.responses:
            overrides["responses_table"] = stores.responses.table_name
        if stores.inference:
            overrides["inference_table"] = stores.inference.table_name
        return overrides

    def _run_upgrade_cmd(self, args: argparse.Namespace) -> None:
        from alembic import command
        from alembic.config import Config

        config_path = self._resolve_config(args)
        postgres_backends = self._get_postgres_urls(config_path)

        if not postgres_backends:
            logger.info("No PostgreSQL backends found in config. Nothing to migrate.")
            return

        table_overrides = self._get_table_name_overrides(config_path)
        migrations_dir = str(Path(__file__).parent.parent / "core" / "storage" / "migrations")

        for backend_name, dsn in postgres_backends:
            logger.info("Running migrations", backend=backend_name)
            alembic_cfg = Config()
            alembic_cfg.set_main_option("script_location", migrations_dir)
            alembic_cfg.set_main_option("sqlalchemy.url", dsn)
            for key, value in table_overrides.items():
                alembic_cfg.set_main_option(f"x_{key}", value)
            try:
                command.upgrade(alembic_cfg, "head")
                logger.info("Migrations complete", backend=backend_name)
            except Exception:
                logger.exception("Failed to run migrations", backend=backend_name)
                sys.exit(1)

    def _run_current_cmd(self, args: argparse.Namespace) -> None:
        from alembic import command
        from alembic.config import Config

        config_path = self._resolve_config(args)
        postgres_backends = self._get_postgres_urls(config_path)

        if not postgres_backends:
            logger.info("No PostgreSQL backends found in config.")
            return

        migrations_dir = str(Path(__file__).parent.parent / "core" / "storage" / "migrations")

        for backend_name, dsn in postgres_backends:
            alembic_cfg = Config()
            alembic_cfg.set_main_option("script_location", migrations_dir)
            alembic_cfg.set_main_option("sqlalchemy.url", dsn)
            print(f"Backend '{backend_name}':")
            command.current(alembic_cfg, verbose=True)

    def _run_history_cmd(self, args: argparse.Namespace) -> None:
        from alembic import command
        from alembic.config import Config

        migrations_dir = str(Path(__file__).parent.parent / "core" / "storage" / "migrations")
        alembic_cfg = Config()
        alembic_cfg.set_main_option("script_location", migrations_dir)
        command.history(alembic_cfg, verbose=True)
