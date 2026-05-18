# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""Tests for ogx db CLI subcommands."""

import argparse

from ogx.cli.db import Db


def test_db_subcommand_creates_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    db = Db(subparsers)
    assert db.parser is not None


def test_db_upgrade_subcommand_exists():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    Db(subparsers)
    args = parser.parse_args(["db", "upgrade"])
    assert hasattr(args, "func")


def test_db_current_subcommand_exists():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    Db(subparsers)
    args = parser.parse_args(["db", "current"])
    assert hasattr(args, "func")


def test_db_history_subcommand_exists():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    Db(subparsers)
    args = parser.parse_args(["db", "history"])
    assert hasattr(args, "func")


def test_db_upgrade_accepts_config_path():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    Db(subparsers)
    args = parser.parse_args(["db", "upgrade", "/path/to/config.yaml"])
    assert args.config == "/path/to/config.yaml"
