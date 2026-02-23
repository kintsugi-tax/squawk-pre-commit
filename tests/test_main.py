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


def make_result(returncode=0, stdout="", stderr=""):
    return type(
        "Result", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr}
    )()


def fake_subprocess(
    alembic_result=None,
    squawk_result=None,
    git_exists_on_branch=False,
    git_branch_valid=True,
):
    """Return a side_effect function that dispatches based on the command."""
    alembic_res = alembic_result or make_result(stdout="CREATE TABLE foo (id int);\n")
    squawk_res = squawk_result or make_result()

    def side_effect(cmd, **kwargs):
        if cmd[0] == "git":
            if "rev-parse" in cmd:
                return make_result(returncode=0 if git_branch_valid else 1)
            return make_result(returncode=0 if git_exists_on_branch else 1)
        if cmd[0] == "alembic":
            return alembic_res
        if cmd[0] == "squawk":
            return squawk_res
        raise ValueError(f"unexpected command: {cmd}")

    return side_effect


def test_no_files(repo):
    with patch("sys.argv", ["squawk-alembic"]):
        assert main() == 0


def test_no_alembic_ini(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with patch("sys.argv", ["squawk-alembic", "some_file.py"]):
        assert main() == 1
    captured = capsys.readouterr()
    assert "could not find alembic.ini" in captured.err


def test_file_outside_migrations_skipped(repo):
    other = repo / "other.py"
    other.write_text("op.execute('DROP TABLE foo')")
    with patch("sys.argv", ["squawk-alembic", "other.py"]):
        assert main() == 0


def test_squawk_success(repo):
    path = write_migration(
        repo,
        "002_raw_sql.py",
        """
        revision = 'abc123'
        down_revision = 'def456'

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE foo (id int)")
        """,
    )
    with (
        patch("sys.argv", ["squawk-alembic", path]),
        patch("subprocess.run", side_effect=fake_subprocess()) as mock_run,
    ):
        assert main() == 0
        assert mock_run.call_count == 2
        alembic_call = mock_run.call_args_list[0][0][0]
        assert alembic_call[0] == "alembic"
        assert "def456:abc123" in alembic_call
        squawk_call = mock_run.call_args_list[1][0][0]
        assert squawk_call[0] == "squawk"


def test_squawk_failure(repo, capsys):
    path = write_migration(
        repo,
        "003_bad_sql.py",
        """
        revision = 'abc123'
        down_revision = 'def456'

        from alembic import op

        def upgrade():
            op.execute("ALTER TABLE foo ADD COLUMN bar int")
        """,
    )
    with (
        patch("sys.argv", ["squawk-alembic", path]),
        patch(
            "subprocess.run",
            side_effect=fake_subprocess(
                squawk_result=make_result(returncode=1, stdout="some squawk warning\n"),
            ),
        ),
    ):
        assert main() == 1
    captured = capsys.readouterr()
    assert "some squawk warning" in captured.out


def test_alembic_failure_skips_file(repo, capsys):
    path = write_migration(
        repo,
        "004_alembic_fail.py",
        """
        revision = 'abc123'
        down_revision = 'def456'

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE foo (id int)")
        """,
    )
    with (
        patch("sys.argv", ["squawk-alembic", path]),
        patch(
            "subprocess.run",
            side_effect=fake_subprocess(
                alembic_result=make_result(returncode=1, stderr="alembic error\n"),
            ),
        ),
    ):
        assert main() == 0
    captured = capsys.readouterr()
    assert "alembic upgrade --sql failed" in captured.err


def test_missing_alembic_binary(repo, capsys):
    path = write_migration(
        repo,
        "005_no_alembic.py",
        """
        revision = 'abc123'
        down_revision = 'def456'

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE foo (id int)")
        """,
    )
    with (
        patch("sys.argv", ["squawk-alembic", path]),
        patch("subprocess.run", side_effect=FileNotFoundError),
    ):
        assert main() == 0
    captured = capsys.readouterr()
    assert "alembic not found" in captured.err


def test_merge_migration_skipped(repo):
    path = write_migration(
        repo,
        "006_merge.py",
        """
        revision = 'merge001'
        down_revision = ('abc123', 'def456')
        branch_labels = None
        depends_on = None

        def upgrade():
            pass
        """,
    )
    with (
        patch("sys.argv", ["squawk-alembic", path]),
        patch("subprocess.run") as mock_run,
    ):
        assert main() == 0
        mock_run.assert_not_called()


def test_first_migration_uses_base(repo):
    path = write_migration(
        repo,
        "007_first.py",
        """
        revision = 'first001'
        down_revision = None

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE foo (id int)")
        """,
    )
    with (
        patch("sys.argv", ["squawk-alembic", path]),
        patch("subprocess.run", side_effect=fake_subprocess()) as mock_run,
    ):
        assert main() == 0
        alembic_call = mock_run.call_args_list[0][0][0]
        assert "base:first001" in alembic_call


def test_diff_branch_skips_existing_file(repo):
    path = write_migration(
        repo,
        "008_existing.py",
        """
        revision = 'exists01'
        down_revision = 'prev001'

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE foo (id int)")
        """,
    )
    with (
        patch("sys.argv", ["squawk-alembic", "--diff-branch", "main", path]),
        patch(
            "subprocess.run",
            side_effect=fake_subprocess(git_exists_on_branch=True),
        ) as mock_run,
    ):
        assert main() == 0
        # git rev-parse (validation) + git cat-file (exists check), no alembic or squawk
        assert mock_run.call_count == 2
        assert mock_run.call_args_list[0][0][0][0] == "git"
        assert mock_run.call_args_list[1][0][0][0] == "git"


def test_diff_branch_lints_new_file(repo):
    path = write_migration(
        repo,
        "009_new.py",
        """
        revision = 'new001'
        down_revision = 'prev001'

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE foo (id int)")
        """,
    )
    with (
        patch("sys.argv", ["squawk-alembic", "--diff-branch", "main", path]),
        patch(
            "subprocess.run",
            side_effect=fake_subprocess(git_exists_on_branch=False),
        ) as mock_run,
    ):
        assert main() == 0
        # git rev-parse + git cat-file + alembic + squawk = 4 calls
        assert mock_run.call_count == 4


def test_diff_branch_nonexistent_branch_errors(repo, capsys):
    path = write_migration(
        repo,
        "011_nonexistent.py",
        """
        revision = 'non001'
        down_revision = 'prev001'

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE foo (id int)")
        """,
    )
    with (
        patch("sys.argv", ["squawk-alembic", "--diff-branch", "nonexistent", path]),
        patch(
            "subprocess.run",
            side_effect=fake_subprocess(git_branch_valid=False),
        ) as mock_run,
    ):
        assert main() == 1
        # Only the git rev-parse validation call, then early exit
        assert mock_run.call_count == 1
    captured = capsys.readouterr()
    assert "not found in git" in captured.err


def test_without_diff_branch_lints_all(repo):
    path = write_migration(
        repo,
        "010_all.py",
        """
        revision = 'all001'
        down_revision = 'prev001'

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE foo (id int)")
        """,
    )
    with (
        patch("sys.argv", ["squawk-alembic", path]),
        patch("subprocess.run", side_effect=fake_subprocess()) as mock_run,
    ):
        assert main() == 0
        # No git call, just alembic + squawk = 2 calls
        assert mock_run.call_count == 2
