# ogx db — Database Management

The `ogx db` command manages PostgreSQL schema migrations. Run it before starting the server after an OGX version upgrade.

## Commands

### `ogx db upgrade`

Apply all pending schema migrations to PostgreSQL backends.

```bash
ogx db upgrade <config.yaml>
```

- Loads the server config to discover PostgreSQL backends
- Runs Alembic migrations against each unique PostgreSQL DSN
- Exits with code 0 on success, non-zero on failure

The config argument is optional if the `OGX_CONFIG` environment variable is set.

### `ogx db current`

Show the current schema revision for each PostgreSQL backend.

```bash
ogx db current <config.yaml>
```

### `ogx db history`

Show the migration revision history. Does not require a database connection.

```bash
ogx db history
```

## Startup Check

The OGX server checks the schema version on startup. If the database is behind the expected revision, the server refuses to start with an error:

```text
Database schema is behind. Run 'ogx db upgrade' before starting the server.
```

This check only applies to PostgreSQL backends. SQLite backends use runtime schema creation and skip the check.

## When to Run

Run `ogx db upgrade` in these situations:

- **After upgrading OGX** to a new version that includes schema changes
- **On first deployment** with a new PostgreSQL database
- **After adding a new PostgreSQL backend** to the config

The command is idempotent. Running it against an already up-to-date database is safe and fast.
