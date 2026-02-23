"""Tests for the main hook entrypoint."""

import textwrap
from unittest.mock import patch

import pytest

from squawk_alembic.hook import main


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """Set up a fake repo with alembic config and a versions directory."""
    monkeypatch.chdir(tmp_path)
    versions = tmp_path / "migrations" / "versions"
    versions.mkdir(parents=True)
    (tmp_path / "alembic.ini").write_text("[alembic]\nscript_location = ./migrations\n")
    return tmp_path


def write_migration(repo, filename, source):
    path = repo / "migrations" / "versions" / filename
    path.write_text(textwrap.dedent(source))
    return f"migrations/versions/{filename}"


class TestMain:
    def test_no_files(self, repo):
        with patch("sys.argv", ["squawk-alembic"]):
            assert main() == 0

    def test_no_alembic_ini(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("sys.argv", ["squawk-alembic", "some_file.py"]):
            assert main() == 0

    def test_file_outside_migrations_skipped(self, repo):
        other = repo / "other.py"
        other.write_text("op.execute('DROP TABLE foo')")
        with patch("sys.argv", ["squawk-alembic", "other.py"]):
            assert main() == 0

    def test_migration_with_no_sql_skipped(self, repo):
        path = write_migration(
            repo,
            "001_add_column.py",
            """
            from alembic import op
            import sqlalchemy as sa

            def upgrade():
                op.add_column('users', sa.Column('email', sa.String(255)))
            """,
        )
        with patch("sys.argv", ["squawk-alembic", path]):
            assert main() == 0

    def test_squawk_success(self, repo):
        path = write_migration(
            repo,
            "002_raw_sql.py",
            """
            from alembic import op

            def upgrade():
                op.execute("CREATE TABLE foo (id int)")
            """,
        )
        mock_result = type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "",
                "stderr": "",
            },
        )()
        with (
            patch("sys.argv", ["squawk-alembic", path]),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            assert main() == 0
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args[0] == "squawk"

    def test_squawk_failure(self, repo, capsys):
        path = write_migration(
            repo,
            "003_bad_sql.py",
            """
            from alembic import op

            def upgrade():
                op.execute("ALTER TABLE foo ADD COLUMN bar int")
            """,
        )
        mock_result = type(
            "Result",
            (),
            {
                "returncode": 1,
                "stdout": "some squawk warning\n",
                "stderr": "",
            },
        )()
        with (
            patch("sys.argv", ["squawk-alembic", path]),
            patch("subprocess.run", return_value=mock_result),
        ):
            assert main() == 1
        captured = capsys.readouterr()
        assert "some squawk warning" in captured.out
