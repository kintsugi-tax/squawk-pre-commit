"""Pre-commit hook that generates DDL via alembic upgrade --sql and lints with squawk."""

import ast
import configparser
import os
import subprocess
import sys
import tempfile
from pathlib import Path


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


def check_autocommit_blocks(filepath):
    """Check that CONCURRENTLY operations are inside autocommit blocks."""
    with open(filepath) as f:
        try:
            tree = ast.parse(f.read())
        except SyntaxError:
            return []

    checker = _AutocommitChecker()
    checker.visit(tree)
    return checker.warnings


def _has_concurrent_kwarg(node):
    """Check if an AST Call node has postgresql_concurrently=True."""
    for kw in node.keywords:
        if (
            kw.arg == "postgresql_concurrently"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
        ):
            return True
    return False


class _AutocommitChecker(ast.NodeVisitor):
    def __init__(self):
        self.warnings = []
        self._in_autocommit = False

    def visit_With(self, node):
        is_autocommit = any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "autocommit_block"
            for item in node.items
        )
        if is_autocommit:
            old = self._in_autocommit
            self._in_autocommit = True
            self.generic_visit(node)
            self._in_autocommit = old
        else:
            self.generic_visit(node)

    def visit_Call(self, node):
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "op"
        ):
            # op.execute("...CONCURRENTLY...")
            if node.func.attr == "execute" and node.args:
                sql = _extract_string(node.args[0])
                if sql and "concurrently" in sql.lower() and not self._in_autocommit:
                    self.warnings.append(node.lineno)

            # op.create_index(..., postgresql_concurrently=True)
            # op.drop_index(..., postgresql_concurrently=True)
            if node.func.attr in ("create_index", "drop_index"):
                if _has_concurrent_kwarg(node) and not self._in_autocommit:
                    self.warnings.append(node.lineno)

        self.generic_visit(node)


def _extract_string(node):
    """Extract a string value from an AST node, handling common wrappers."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value

    if isinstance(node, ast.Call) and node.args:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "text":
            return _extract_string(node.args[0])
        if isinstance(node.func, ast.Name) and node.func.id == "text":
            return _extract_string(node.args[0])

    return None


def main():
    files = sys.argv[1:]
    if not files:
        return 0

    migrations_path = find_migrations_path()
    if not migrations_path:
        print(
            "squawk-alembic: could not find alembic.ini or parse script_location",
            file=sys.stderr,
        )
        return 0

    exit_code = 0

    for filepath in files:
        try:
            Path(filepath).relative_to(migrations_path)
        except ValueError:
            continue

        autocommit_warnings = check_autocommit_blocks(filepath)
        for lineno in autocommit_warnings:
            print(
                f"{filepath}:{lineno}: CONCURRENTLY operation outside autocommit_block()"
            )
            exit_code = 1

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
