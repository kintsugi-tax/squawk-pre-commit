"""Pre-commit hook that generates DDL via alembic upgrade --sql and lints with squawk."""

import argparse
import ast
import configparser
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_BRANCH_RE = re.compile(r"^[a-zA-Z0-9._/\-]+$")


def find_migrations_path():
    """Auto-detect the alembic migrations versions directory from alembic.ini."""
    config_path = Path("alembic.ini")
    if not config_path.exists():
        return None

    config = configparser.ConfigParser()
    config.read(config_path)

    try:
        script_location = config.get("alembic", "script_location")
    except (configparser.NoSectionError, configparser.NoOptionError):
        return None

    script_location = script_location.removeprefix("./")
    versions_path = Path(script_location) / "versions"

    if versions_path.is_dir():
        return versions_path

    return None


class RevisionInfo:
    __slots__ = ("revision", "down_revision", "is_merge")

    def __init__(self, revision, down_revision, is_merge):
        self.revision = revision
        self.down_revision = down_revision
        self.is_merge = is_merge


def extract_revision_info(filepath):
    """Parse a migration file to extract revision and down_revision from module-level assignments."""
    with open(filepath) as f:
        try:
            tree = ast.parse(f.read())
        except SyntaxError:
            return None

    revision = None
    down_revision = None

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue

        name = node.targets[0].id
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
                values = []
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


def generate_sql(filepath):
    """Run alembic upgrade --sql to generate the complete DDL for a migration."""
    info = extract_revision_info(filepath)
    if info is None:
        return None

    if info.is_merge:
        return None

    base = info.down_revision if info.down_revision else "base"
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
    except FileNotFoundError:
        print(
            "squawk-alembic: alembic not found. Ensure alembic is installed in your environment.",
            file=sys.stderr,
        )
        return None

    if result.returncode != 0:
        print(
            f"squawk-alembic: alembic upgrade --sql failed for {filepath}:\n{result.stderr}",
            file=sys.stderr,
        )
        return None

    return result.stdout


def validate_branch(branch):
    """Validate that a branch name is safe and exists in git."""
    if not _BRANCH_RE.match(branch):
        print(
            f"squawk-alembic: invalid branch name: {branch!r}",
            file=sys.stderr,
        )
        return False
    result = subprocess.run(
        ["git", "rev-parse", "--verify", branch],
        capture_output=True,
    )
    if result.returncode != 0:
        print(
            f"squawk-alembic: branch '{branch}' not found in git",
            file=sys.stderr,
        )
        return False
    return True


def file_exists_on_branch(filepath, branch):
    """Check if a file exists on the given git branch."""
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{branch}:{filepath}"],
        capture_output=True,
    )
    return result.returncode == 0


def main():
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
            Path(filepath).relative_to(migrations_path)
        except ValueError:
            continue

        if args.diff_branch and file_exists_on_branch(filepath, args.diff_branch):
            continue

        sql = generate_sql(filepath)
        if not sql:
            continue

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
                exit_code = 1
        except FileNotFoundError:
            print(
                "squawk-alembic: squawk not found. Install with: pip install squawk-cli",
                file=sys.stderr,
            )
            return 1
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
