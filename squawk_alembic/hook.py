"""Pre-commit hook that extracts SQL from Alembic migrations and lints with squawk."""

import ast
import configparser
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


def extract_sql(filepath):
    """Parse a migration file and extract SQL strings from op.execute() calls."""
    with open(filepath) as f:
        try:
            tree = ast.parse(f.read())
        except SyntaxError:
            return []

    statements = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "op"
            and node.args
        ):
            continue

        sql = _extract_string(node.args[0])
        if sql:
            statements.append(sql)

    return statements


def _extract_string(node):
    """Extract a string value from an AST node, handling common wrappers."""
    # Direct string literal: op.execute("SQL")
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value

    # sa.text("SQL") or text("SQL")
    if isinstance(node, ast.Call) and node.args:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "text":
            return _extract_string(node.args[0])
        if isinstance(node.func, ast.Name) and node.func.id == "text":
            return _extract_string(node.args[0])

    return None


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
            and node.func.attr == "execute"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "op"
            and node.args
        ):
            sql = _extract_string(node.args[0])
            if sql and "concurrently" in sql.lower() and not self._in_autocommit:
                self.warnings.append(node.lineno)
        self.generic_visit(node)


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

        statements = extract_sql(filepath)
        if not statements:
            continue

        combined = "\n".join(statements)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".sql", delete=False) as tmp:
            tmp.write(combined)
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
