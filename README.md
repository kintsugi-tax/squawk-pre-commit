# Kintsugi Squawk

A [pre-commit](https://pre-commit.com/) hook that lints SQL in [Alembic](https://alembic.sqlalchemy.org/) migrations using [squawk](https://squawkhq.com/), a PostgreSQL migration linter.

Squawk operates on raw SQL files, but Alembic migrations are Python. This hook bridges the gap by generating DDL via `alembic upgrade --sql` (offline mode) and passing the complete SQL output to squawk for analysis. This captures all SQL statements a migration produces, including ORM operations like `op.create_index()`, `op.create_table()`, and `op.alter_column()`.

The hook also checks that concurrent index operations (`CONCURRENTLY` in `op.execute()` or `postgresql_concurrently=True` in `op.create_index()` / `op.drop_index()`) are wrapped in `autocommit_block()`.

## Usage

Add the following to your `.pre-commit-config.yaml`:

```yaml
repos:
    - repo: https://github.com/kintsugi-tax/kintsugi-squawk
      rev: v0.2.0
      hooks:
          - id: squawk-alembic
```

No additional configuration is required. The hook auto-detects your migrations directory by reading `script_location` from `alembic.ini`. The consumer's `alembic` must be available on PATH (the hook calls it via subprocess).

## How It Works

When pre-commit runs, the hook:

1. Parses `alembic.ini` to find the migrations `versions/` directory
2. Filters staged files to only those under that directory
3. Checks for concurrent operations outside `autocommit_block()`
4. Runs `alembic upgrade --sql` to generate the complete DDL for each migration
5. Pipes the generated SQL to squawk for linting

Merge migrations (where `down_revision` is a tuple) are skipped since they produce no DDL.

## Squawk Configuration

Squawk reads its configuration from `.squawk.toml` in the consumer repo root. See the [squawk docs](https://squawkhq.com/docs/configuration/) for available options.

## Local Development

**Prerequisites:**

* Python (version 3.12)
* Poetry
* squawk-cli (`pip install squawk-cli`)

**Steps:**

1. Install dependencies: `poetry install`
2. Activate the virtual environment: `source .venv/bin/activate`
3. Install the pre-commit hooks: `pre-commit install`
4. Run tests: `poetry run pytest tests/ -v`

To test the hook against a consumer repo locally:

```bash
cd /path/to/consumer-repo
pre-commit try-repo /path/to/kintsugi-squawk squawk-alembic --all-files
```
