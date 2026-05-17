#!/bin/bash
# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

# Block SQL data operations (fetch_all, fetch_one, insert, update, delete)
# inside initialize() methods in provider and core code.
#
# These operations trigger _ensure_engine() which binds the SQL engine to the
# current event loop. During Stack.initialize() this is a temporary loop —
# the engine will fail at request time with "Future attached to a different loop".
#
# Allowed: create_table(), add_column_if_not_exists() (metadata-only, no engine).
# Blocked: fetch_all(), fetch_one(), insert(), update(), delete() (trigger engine).

set -euo pipefail

BLOCKED_OPS='\.fetch_all\(|\.fetch_one\(|\.insert\(|\.update\(|\.delete\('
SEARCH_DIRS="src/ogx/providers src/ogx/core"
EXCLUDE_DIR="src/ogx/core/storage"

found_violations=false

for dir in $SEARCH_DIRS; do
    [ -d "$dir" ] || continue

    # Find Python files, excluding the storage implementation itself
    while IFS= read -r file; do
        # Use awk to detect blocked operations inside initialize() method bodies
        result=$(awk '
            /^[[:space:]]*(async[[:space:]]+)?def[[:space:]]+initialize[[:space:]]*\(/ {
                in_init = 1
                init_indent = 0
                match($0, /^[[:space:]]*/)
                init_indent = RLENGTH
                next
            }
            in_init && /^[[:space:]]*(async[[:space:]]+)?def[[:space:]]+[a-zA-Z_]/ {
                match($0, /^[[:space:]]*/)
                if (RLENGTH <= init_indent) {
                    in_init = 0
                }
            }
            in_init && /\.(fetch_all|fetch_one|insert|update|delete)\(/ {
                # Skip lines that are comments
                stripped = $0
                sub(/^[[:space:]]*/, "", stripped)
                if (substr(stripped, 1, 1) != "#") {
                    printf "%s:%d: %s\n", FILENAME, NR, $0
                }
            }
        ' "$file")

        if [ -n "$result" ]; then
            found_violations=true
            echo "$result"
        fi
    done < <(find "$dir" -name "*.py" -not -path "${EXCLUDE_DIR}/*")
done

if [ "$found_violations" = true ]; then
    echo
    echo "❌ SQL data operations detected inside initialize() methods."
    echo "These trigger _ensure_engine() which binds the SQL engine to the"
    echo "current event loop. During Stack.initialize() this is a temporary"
    echo "loop — the engine will fail at request time."
    echo
    echo "Allowed in initialize(): create_table(), add_column_if_not_exists()"
    echo "Blocked in initialize(): fetch_all(), fetch_one(), insert(), update(), delete()"
    echo
    echo "Move data operations to a separate method called after server startup,"
    echo "or use the lifespan handler."
    exit 1
fi
