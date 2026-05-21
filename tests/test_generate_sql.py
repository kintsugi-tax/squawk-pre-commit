"""Tests for generate_sql, exercising it directly rather than through main()."""

import textwrap
from unittest.mock import patch

import pytest

from squawk_alembic.hook import GenerateSqlError, generate_sql

from .conftest import make_result


def write_file(tmp_path, source):
    path = tmp_path / "migration.py"
    path.write_text(textwrap.dedent(source))
    return str(path)


def test_returns_sql_for_valid_migration(tmp_path):
    path = write_file(
        tmp_path,
        """
        revision = 'abc123'
        down_revision = 'def456'

        def upgrade():
            pass
        """,
    )
    expected_sql = "CREATE TABLE foo (id int);\n"
    with patch(
        "subprocess.run",
        return_value=make_result(stdout=expected_sql),
    ):
        assert generate_sql(path) == expected_sql


def test_returns_none_for_unparseable_file(tmp_path):
    path = write_file(tmp_path, "this is not valid python {{{")
    assert generate_sql(path) is None


def test_returns_none_for_merge_migration(tmp_path):
    path = write_file(
        tmp_path,
        """
        revision = 'merge001'
        down_revision = ('abc123', 'def456')

        def upgrade():
            pass
        """,
    )
    assert generate_sql(path) is None


def test_returns_none_for_missing_revision(tmp_path):
    path = write_file(
        tmp_path,
        """
        down_revision = 'def456'

        def upgrade():
            pass
        """,
    )
    assert generate_sql(path) is None


def test_uses_base_when_down_revision_is_none(tmp_path):
    path = write_file(
        tmp_path,
        """
        revision = 'first001'
        down_revision = None

        def upgrade():
            pass
        """,
    )
    with patch(
        "subprocess.run",
        return_value=make_result(stdout="CREATE TABLE foo (id int);\n"),
    ) as mock_run:
        generate_sql(path)
        cmd = mock_run.call_args[0][0]
        assert "base:first001" in cmd


def test_raises_on_alembic_failure(tmp_path):
    path = write_file(
        tmp_path,
        """
        revision = 'abc123'
        down_revision = 'def456'

        def upgrade():
            pass
        """,
    )
    with patch(
        "subprocess.run",
        return_value=make_result(returncode=1, stderr="some error"),
    ):
        with pytest.raises(GenerateSqlError, match="alembic upgrade --sql failed"):
            generate_sql(path)


def test_raises_when_alembic_not_found(tmp_path):
    path = write_file(
        tmp_path,
        """
        revision = 'abc123'
        down_revision = 'def456'

        def upgrade():
            pass
        """,
    )
    with patch("subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(GenerateSqlError, match="alembic not found"):
            generate_sql(path)


def test_provides_dummy_database_url_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    path = write_file(
        tmp_path,
        """
        revision = 'abc123'
        down_revision = 'def456'

        def upgrade():
            pass
        """,
    )
    with patch(
        "subprocess.run",
        return_value=make_result(stdout="SQL;\n"),
    ) as mock_run:
        generate_sql(path)
        env = mock_run.call_args[1]["env"]
        assert env["DATABASE_URL"] == "postgresql://localhost/lint"


def test_preserves_existing_database_url(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://real-host/real-db")
    path = write_file(
        tmp_path,
        """
        revision = 'abc123'
        down_revision = 'def456'

        def upgrade():
            pass
        """,
    )
    with patch(
        "subprocess.run",
        return_value=make_result(stdout="SQL;\n"),
    ) as mock_run:
        generate_sql(path)
        env = mock_run.call_args[1]["env"]
        assert env["DATABASE_URL"] == "postgresql://real-host/real-db"
