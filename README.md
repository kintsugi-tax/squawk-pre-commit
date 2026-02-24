# squawk-pre-commit

A [pre-commit](https://pre-commit.com/) hook that lints SQL in [Alembic](https://alembic.sqlalchemy.org/) migrations using [squawk](https://squawkhq.com/), a PostgreSQL migration linter.

Squawk operates on raw SQL files, but Alembic migrations are Python. This hook bridges the gap by generating DDL via `alembic upgrade --sql` (offline mode) and passing the complete SQL output to squawk for analysis. This captures all SQL statements a migration produces, including ORM operations like `op.create_index()`, `op.create_table()`, and `op.alter_column()`.

## Usage

Add the following to your `.pre-commit-config.yaml`:

```yaml
repos:
    - repo: https://github.com/kintsugi-tax/squawk-pre-commit
      rev: v0.3.0
      hooks:
          - id: squawk-alembic
```

No additional configuration is required. The hook auto-detects your migrations directory by reading `script_location` from `alembic.ini`. The consumer's `alembic` must be available on PATH (the hook calls it via subprocess).

### Pinning the squawk version

The hook depends on `squawk-cli >= 2.0`. To pin a specific squawk version (matching your local dev dependency, for example), use `additional_dependencies`:

```yaml
repos:
    - repo: https://github.com/kintsugi-tax/squawk-pre-commit
      rev: v0.3.0
      hooks:
          - id: squawk-alembic
            additional_dependencies: ["squawk-cli==2.41.0"]
```

This overrides the default version and ensures pre-commit uses the exact squawk release you specify.

### Only lint new migrations

To skip migrations that already exist on a branch (useful for repos with existing violations you can't fix immediately), pass `--diff-branch`:

```yaml
repos:
    - repo: https://github.com/kintsugi-tax/squawk-pre-commit
      rev: v0.3.0
      hooks:
          - id: squawk-alembic
            args: [--diff-branch, main]
```

With this flag, the hook checks whether each migration file exists on the specified branch. Files that already exist are skipped. New files (not yet on the branch) are linted. This makes `pre-commit run --all-files` safe to run in repos where older migrations would fail linting.

## How It Works

When pre-commit runs, the hook:

1. Parses `alembic.ini` to find the migrations `versions/` directory
2. Filters staged files to only those under that directory
3. Runs `alembic upgrade --sql` to generate the complete DDL for each migration
4. Pipes the generated SQL to squawk for linting

Merge migrations (where `down_revision` is a tuple) are skipped since they produce no DDL.

## Known Limitations

* The hook runs `alembic upgrade --sql`, which executes your project's `env.py` in offline mode. No database connection is made, but the Python code in `env.py` does run.
* If `DATABASE_URL` is not set, the hook provides a dummy fallback (`postgresql://localhost/lint`) so alembic's offline mode can generate SQL without a real connection string.
* If `alembic upgrade --sql` fails for a migration (e.g. due to missing dependencies or env configuration), the hook prints the error to stderr and fails the run.

## Squawk Configuration

Squawk reads its configuration from `.squawk.toml` in the consumer repo root. See the [squawk docs](https://squawkhq.com/docs/configuration/) for available options.

## Local Development

**Prerequisites:**

* Python 3.10+ (3.12 recommended for development)
* Poetry
* squawk-cli (`pip install squawk-cli`)

**Steps:**

1. Install dependencies: `poetry install`
2. Activate the virtual environment: `source .venv/bin/activate`
3. Install the pre-commit hooks: `pre-commit install`
4. Run tests: `poetry run pytest tests/ -v`

Some integration tests in `tests/test_squawk_config.py` require `squawk` on PATH and are automatically skipped if it is not installed.

To test the hook against a consumer repo locally:

```bash
cd /path/to/consumer-repo
pre-commit try-repo /path/to/squawk-pre-commit squawk-alembic --all-files
```
