"""Pre-commit hook that generates DDL via alembic upgrade --sql and lints with squawk."""

import argparse
import ast
import os
import re
import subprocess
import sys
import tempfile
from configparser import ConfigParser, NoOptionError, NoSectionError
from dataclasses import dataclass
from pathlib import Path

_BRANCH_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/\-]*$")


def find_migrations_path() -> Path | None:
    """Auto-detect the alembic migrations versions directory from alembic.ini."""
    config_path = Path("alembic.ini")
    if not config_path.exists():
        return None

    config = ConfigParser()
    config.read(config_path)

    try:
        script_location = config.get("alembic", "script_location")
    except (NoSectionError, NoOptionError):
        return None

    script_location = script_location.removeprefix("./")
    versions_path = Path(script_location) / "versions"

    if versions_path.is_dir():
        return versions_path

    return None


@dataclass(frozen=True, slots=True)
class RevisionInfo:
    revision: str
    down_revision: str | tuple[str, ...] | None
    is_merge: bool


def extract_revision_info(filepath: str | Path) -> RevisionInfo | None:
    """Parse a migration file to extract revision and down_revision from module-level assignments."""
    with open(filepath) as f:
        try:
            tree = ast.parse(f.read())
        except SyntaxError:
            return None

    revision: str | None = None
    down_revision: str | tuple[str, ...] | None = None

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name) or node.value is None:
                continue
            name = node.target.id
        elif isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            name = node.targets[0].id
        else:
            continue
        if name == "revision":
            if isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str
            ):
                revision = node.value.value
        elif name == "down_revision":
            if isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    down_revision = node.value.value
                elif node.value.value is None:
                    down_revision = None
            elif isinstance(node.value, ast.Tuple):
                values: list[str] = []
                for elt in node.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        values.append(elt.value)
                down_revision = tuple(values)

    if revision is None:
        return None

    is_merge = isinstance(down_revision, tuple)
    return RevisionInfo(
        revision=revision, down_revision=down_revision, is_merge=is_merge
    )


class GenerateSqlError(Exception):
    """Raised when alembic upgrade --sql fails."""


def generate_sql(filepath: str | Path) -> str | None:
    """Run alembic upgrade --sql to generate the complete DDL for a migration.

    Returns the SQL string, or None if the file should be skipped (merge migration,
    unparseable revision). Raises GenerateSqlError if alembic fails.
    """
    info = extract_revision_info(filepath)
    if info is None:
        return None

    if info.is_merge:
        return None

    base = info.down_revision if isinstance(info.down_revision, str) else "base"
    target = f"{base}:{info.revision}"

    env = os.environ.copy()
    if "DATABASE_URL" not in env:
        env["DATABASE_URL"] = "postgresql://localhost/lint"

    try:
        result = subprocess.run(
            ["alembic", "upgrade", target, "--sql"],
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError as exc:
        raise GenerateSqlError(
            "squawk-alembic: alembic not found. Ensure alembic is installed in your environment."
        ) from exc

    if result.returncode != 0:
        raise GenerateSqlError(
            f"squawk-alembic: alembic upgrade --sql failed for {filepath}:\n{result.stderr}"
        )

    return result.stdout


def validate_branch(branch: str) -> bool:
    """Validate that a branch name is safe and exists in git.

    For remote refs (origin/...), attempts a shallow fetch when the ref is
    missing locally, common in CI shallow clones.
    """
    if not _BRANCH_RE.match(branch) or ".." in branch:
        print(
            f"squawk-alembic: invalid branch name: {branch!r}",
            file=sys.stderr,
        )
        return False
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", branch],
            capture_output=True,
        )
    except FileNotFoundError:
        print("squawk-alembic: git not found", file=sys.stderr)
        return False
    if result.returncode == 0:
        return True

    if branch.startswith("origin/"):
        remote_branch = branch.removeprefix("origin/")
        fetch = subprocess.run(
            ["git", "fetch", "origin", remote_branch, "--depth=1"],
            capture_output=True,
        )
        if fetch.returncode == 0:
            return True

    print(
        f"squawk-alembic: branch '{branch}' not found in git",
        file=sys.stderr,
    )
    return False


def file_exists_on_branch(filepath: str, branch: str) -> bool:
    """Check if a file exists on the given git branch."""
    try:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{branch}:{filepath}"],
            capture_output=True,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


class _SquawkNotFound(Exception):
    pass


def _lint_file(filepath: str, migrations_path: Path, diff_branch: str | None) -> int:
    """Lint a single migration file. Returns 0 on success/skip, 1 on failure.

    Raises _SquawkNotFound if the squawk binary is missing.
    """
    try:
        Path(filepath).relative_to(migrations_path)
    except ValueError:
        return 0

    if diff_branch and file_exists_on_branch(filepath, diff_branch):
        return 0

    try:
        sql = generate_sql(filepath)
    except GenerateSqlError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(
            f"squawk-alembic: cannot read migration file: {exc}",
            file=sys.stderr,
        )
        return 1

    if not sql:
        return 0

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False) as tmp:
        tmp.write(sql)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["squawk", tmp_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            output = result.stdout.replace(tmp_path, filepath)
            error = result.stderr.replace(tmp_path, filepath)
            if output:
                print(output)
            if error:
                print(error, file=sys.stderr)
            return 1
    except FileNotFoundError:
        # Translate the low-level "squawk binary missing" OSError into our domain
        # error; the original FileNotFoundError is an implementation detail, so
        # suppress its chain with `from None`.
        raise _SquawkNotFound from None
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return 0


def main() -> int:
    """CLI entrypoint. Returns 0 on success, 1 on any failure."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--diff-branch",
        default=None,
        help="Only lint migration files that don't exist on this branch.",
    )
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()

    if not args.files:
        return 0

    if args.diff_branch and not validate_branch(args.diff_branch):
        return 1

    migrations_path = find_migrations_path()
    if not migrations_path:
        print(
            "squawk-alembic: could not find alembic.ini or parse script_location",
            file=sys.stderr,
        )
        return 1

    exit_code = 0

    for filepath in args.files:
        try:
            result = _lint_file(filepath, migrations_path, args.diff_branch)
        except _SquawkNotFound:
            print(
                "squawk-alembic: squawk not found. Install with: pip install squawk-cli",
                file=sys.stderr,
            )
            return 1
        if result != 0:
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
