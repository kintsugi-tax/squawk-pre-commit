# Kintsugi Squawk

A [pre-commit](https://pre-commit.com/) hook that lints SQL in [Alembic](https://alembic.sqlalchemy.org/) migrations using [squawk](https://squawkhq.com/), a PostgreSQL migration linter.

Squawk operates on raw SQL files, but Alembic migrations are Python. This hook bridges the gap by extracting SQL from `op.execute()` calls in migration files and passing it to squawk for analysis.

## Usage

Add the following to your `.pre-commit-config.yaml`:

```yaml
repos:
    - repo: https://github.com/kintsugi-tax/kintsugi-squawk
      rev: v0.1.0
      hooks:
          - id: squawk-alembic
```

No additional configuration is required. The hook auto-detects your migrations directory by reading `script_location` from `alembic.ini`.

## How It Works

When pre-commit runs, the hook:

1. Parses `alembic.ini` to find the migrations `versions/` directory
2. Filters staged files to only those under that directory
3. Extracts SQL strings from `op.execute()` calls using Python's AST parser
4. Pipes the extracted SQL to squawk for linting

The hook handles common patterns including `op.execute("...")`, `op.execute(sa.text("..."))`, triple-quoted strings, and implicit string concatenation.

ORM-level operations like `op.add_column()` and `op.create_table()` are not linted, since they don't contain raw SQL. These produce safe, predictable DDL that squawk is less likely to flag.

## Squawk Configuration

Squawk reads its configuration from `.squawk.toml` in the consumer repo root. See the [squawk docs](https://squawkhq.com/docs/configuration/) for available options.

## Local Development

**Prerequisites:**

* Python (version 3.12)
* Poetry

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
