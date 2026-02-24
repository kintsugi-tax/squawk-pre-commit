"""Integration tests verifying squawk behavior with and without .squawk.toml configuration."""

import shutil
import subprocess

from pytest import fixture, mark

pytestmark = mark.skipif(
    shutil.which("squawk") is None, reason="squawk not installed"
)


SQL = "ALTER TABLE foo ADD COLUMN bar text;\n"


@fixture()
def sql_file(tmp_path):
    path = tmp_path / "migration.sql"
    path.write_text(SQL)
    return path


def test_without_config_flags_prefer_robust_stmts(tmp_path, sql_file):
    """Without assume_in_transaction, squawk flags prefer-robust-stmts."""
    result = subprocess.run(
        ["squawk", str(sql_file)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode != 0
    assert "prefer-robust-stmts" in result.stdout


def test_with_assume_in_transaction_suppresses_prefer_robust_stmts(tmp_path, sql_file):
    """With assume_in_transaction = true, squawk suppresses prefer-robust-stmts."""
    # require-timeout-settings fires independently of assume_in_transaction,
    # so we exclude it here to isolate the prefer-robust-stmts behavior.
    (tmp_path / ".squawk.toml").write_text(
        'assume_in_transaction = true\nexcluded_rules = ["require-timeout-settings"]\n'
    )
    result = subprocess.run(
        ["squawk", str(sql_file)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "prefer-robust-stmts" not in result.stdout
