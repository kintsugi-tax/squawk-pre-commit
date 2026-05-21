"""Tests for the main hook entrypoint."""

import os
import sys
from unittest.mock import patch

from squawk_alembic.hook import main

from .conftest import fake_subprocess, make_result, write_migration


def test_no_files(repo, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["squawk-alembic"])
    assert main() == 0


def test_no_alembic_ini(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", "some_file.py"])
    assert main() == 1
    captured = capsys.readouterr()
    assert "could not find alembic.ini" in captured.err


def test_file_outside_migrations_skipped(repo, monkeypatch):
    other = repo / "other.py"
    other.write_text("op.execute('DROP TABLE foo')")
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", "other.py"])
    assert main() == 0


@patch("subprocess.run")
def test_squawk_success(mock_run, repo, monkeypatch):
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
    mock_run.side_effect = fake_subprocess()
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", path])
    assert main() == 0
    assert mock_run.call_count == 2
    alembic_call = mock_run.call_args_list[0][0][0]
    assert alembic_call[0] == "alembic"
    assert "def456:abc123" in alembic_call
    squawk_call = mock_run.call_args_list[1][0][0]
    assert squawk_call[0] == "squawk"


@patch("subprocess.run")
def test_squawk_failure(mock_run, repo, capsys, monkeypatch):
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
    mock_run.side_effect = fake_subprocess(
        squawk_result=make_result(returncode=1, stdout="some squawk warning\n"),
    )
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", path])
    assert main() == 1
    captured = capsys.readouterr()
    assert "some squawk warning" in captured.out


@patch("subprocess.run")
def test_squawk_failure_replaces_tmp_path_in_output(
    mock_run, repo, capsys, monkeypatch
):
    """Squawk output should show the original migration path, not the temp file path."""
    path = write_migration(
        repo,
        "020_path_rewrite.py",
        """
        revision = 'rw001'
        down_revision = 'prev001'

        from alembic import op

        def upgrade():
            op.execute("ALTER TABLE foo ADD COLUMN bar int")
        """,
    )

    def side_effect(cmd, **kwargs):
        if cmd[0] == "alembic":
            return make_result(stdout="ALTER TABLE foo ADD COLUMN bar int;\n")
        if cmd[0] == "squawk":
            tmp = cmd[1]
            return make_result(
                returncode=1,
                stdout=f"{tmp}:1: warning: prefer-robust-stmts\n",
                stderr=f"error in {tmp}\n",
            )
        raise ValueError(f"unexpected command: {cmd}")

    mock_run.side_effect = side_effect
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", path])
    assert main() == 1
    captured = capsys.readouterr()
    assert path in captured.out
    assert path in captured.err
    assert "/tmp/" not in captured.out
    assert "/tmp/" not in captured.err


@patch("subprocess.run")
def test_alembic_failure_fails_run(mock_run, repo, capsys, monkeypatch):
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
    mock_run.side_effect = fake_subprocess(
        alembic_result=make_result(returncode=1, stderr="alembic error\n"),
    )
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", path])
    assert main() == 1
    captured = capsys.readouterr()
    assert "alembic upgrade --sql failed" in captured.err


def test_unreadable_migration_file(repo, capsys, monkeypatch):
    """A migration file that can't be opened should produce a clear error, not a traceback."""
    path = write_migration(
        repo,
        "026_unreadable.py",
        """
        revision = 'ur001'
        down_revision = 'prev001'

        def upgrade():
            pass
        """,
    )
    unreadable = repo / "migrations" / "versions" / "026_unreadable.py"
    os.chmod(unreadable, 0o000)
    try:
        monkeypatch.setattr(sys, "argv", ["squawk-alembic", path])
        assert main() == 1
        captured = capsys.readouterr()
        assert "cannot read migration file" in captured.err
    finally:
        os.chmod(unreadable, 0o644)


@patch("subprocess.run")
def test_missing_alembic_binary(mock_run, repo, capsys, monkeypatch):
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

    def alembic_not_found(cmd, **kwargs):
        if cmd[0] == "alembic":
            raise FileNotFoundError
        raise ValueError(f"unexpected command: {cmd}")

    mock_run.side_effect = alembic_not_found
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", path])
    assert main() == 1
    captured = capsys.readouterr()
    assert "alembic not found" in captured.err


@patch("subprocess.run")
def test_missing_squawk_binary(mock_run, repo, capsys, monkeypatch):
    """When squawk is not installed, the hook should fail with a helpful message."""
    path = write_migration(
        repo,
        "021_no_squawk.py",
        """
        revision = 'ns001'
        down_revision = 'prev001'

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE foo (id int)")
        """,
    )

    def squawk_not_found(cmd, **kwargs):
        if cmd[0] == "alembic":
            return make_result(stdout="CREATE TABLE foo (id int);\n")
        if cmd[0] == "squawk":
            raise FileNotFoundError
        raise ValueError(f"unexpected command: {cmd}")

    mock_run.side_effect = squawk_not_found
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", path])
    assert main() == 1
    captured = capsys.readouterr()
    assert "squawk not found" in captured.err


@patch("subprocess.run")
def test_merge_migration_skipped(mock_run, repo, monkeypatch):
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
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", path])
    assert main() == 0
    mock_run.assert_not_called()


@patch("subprocess.run")
def test_first_migration_uses_base(mock_run, repo, monkeypatch):
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
    mock_run.side_effect = fake_subprocess()
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", path])
    assert main() == 0
    alembic_call = mock_run.call_args_list[0][0][0]
    assert "base:first001" in alembic_call


@patch("subprocess.run")
def test_multiple_files_all_pass(mock_run, repo, monkeypatch):
    """All files should be processed when multiple are passed."""
    path1 = write_migration(
        repo,
        "022_multi_a.py",
        """
        revision = 'ma001'
        down_revision = 'prev001'

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE a (id int)")
        """,
    )
    path2 = write_migration(
        repo,
        "023_multi_b.py",
        """
        revision = 'mb001'
        down_revision = 'ma001'

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE b (id int)")
        """,
    )
    mock_run.side_effect = fake_subprocess()
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", path1, path2])
    assert main() == 0
    # alembic + squawk for each file = 4 calls
    assert mock_run.call_count == 4


@patch("subprocess.run")
def test_multiple_files_first_fails_second_still_runs(
    mock_run, repo, capsys, monkeypatch
):
    """A failure in one file should not prevent linting of subsequent files."""
    path1 = write_migration(
        repo,
        "024_fail.py",
        """
        revision = 'f001'
        down_revision = 'prev001'

        from alembic import op

        def upgrade():
            op.execute("ALTER TABLE foo ADD COLUMN bar int")
        """,
    )
    path2 = write_migration(
        repo,
        "025_pass.py",
        """
        revision = 'p001'
        down_revision = 'f001'

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE bar (id int)")
        """,
    )

    call_count = {"alembic": 0}

    def side_effect(cmd, **kwargs):
        if cmd[0] == "alembic":
            call_count["alembic"] += 1
            if call_count["alembic"] == 1:
                return make_result(returncode=1, stderr="alembic error on first\n")
            return make_result(stdout="CREATE TABLE bar (id int);\n")
        if cmd[0] == "squawk":
            return make_result()
        raise ValueError(f"unexpected command: {cmd}")

    mock_run.side_effect = side_effect
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", path1, path2])
    assert main() == 1
    # alembic (fail) + alembic (pass) + squawk (pass) = 3
    assert mock_run.call_count == 3
    captured = capsys.readouterr()
    assert "alembic upgrade --sql failed" in captured.err


@patch("subprocess.run")
def test_diff_branch_skips_existing_file(mock_run, repo, monkeypatch):
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
    mock_run.side_effect = fake_subprocess(git_exists_on_branch=True)
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", "--diff-branch", "main", path])
    assert main() == 0
    # git rev-parse (validation) + git cat-file (exists check), no alembic or squawk
    assert mock_run.call_count == 2
    assert mock_run.call_args_list[0][0][0][0] == "git"
    assert mock_run.call_args_list[1][0][0][0] == "git"


@patch("subprocess.run")
def test_diff_branch_lints_new_file(mock_run, repo, monkeypatch):
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
    mock_run.side_effect = fake_subprocess(git_exists_on_branch=False)
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", "--diff-branch", "main", path])
    assert main() == 0
    # git rev-parse + git cat-file + alembic + squawk = 4 calls
    assert mock_run.call_count == 4


@patch("subprocess.run")
def test_diff_branch_nonexistent_branch_errors(mock_run, repo, capsys, monkeypatch):
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
    mock_run.side_effect = fake_subprocess(git_branch_valid=False)
    monkeypatch.setattr(
        sys, "argv", ["squawk-alembic", "--diff-branch", "nonexistent", path]
    )
    assert main() == 1
    # Only the git rev-parse validation call, then early exit
    assert mock_run.call_count == 1
    captured = capsys.readouterr()
    assert "not found in git" in captured.err


@patch("subprocess.run")
def test_diff_branch_traversal_rejected(mock_run, repo, capsys, monkeypatch):
    path = write_migration(
        repo,
        "013_traversal.py",
        """
        revision = 'trv001'
        down_revision = 'prev001'

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE foo (id int)")
        """,
    )
    monkeypatch.setattr(
        sys, "argv", ["squawk-alembic", "--diff-branch", "refs/../main", path]
    )
    assert main() == 1
    mock_run.assert_not_called()
    captured = capsys.readouterr()
    assert "invalid branch name" in captured.err


@patch("subprocess.run")
def test_diff_branch_missing_git_binary(mock_run, repo, capsys, monkeypatch):
    path = write_migration(
        repo,
        "014_no_git.py",
        """
        revision = 'git001'
        down_revision = 'prev001'

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE foo (id int)")
        """,
    )
    mock_run.side_effect = FileNotFoundError
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", "--diff-branch", "main", path])
    assert main() == 1
    captured = capsys.readouterr()
    assert "git not found" in captured.err


@patch("subprocess.run")
def test_without_diff_branch_lints_all(mock_run, repo, monkeypatch):
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
    mock_run.side_effect = fake_subprocess()
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", path])
    assert main() == 0
    # No git call, just alembic + squawk = 2 calls
    assert mock_run.call_count == 2


@patch("subprocess.run")
def test_origin_branch_shallow_fetch_succeeds(mock_run, repo, monkeypatch):
    """In CI shallow clones, origin/main may not exist locally; the hook should fetch it."""
    path = write_migration(
        repo,
        "016_shallow.py",
        """
        revision = 'sha001'
        down_revision = 'prev001'

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE foo (id int)")
        """,
    )
    mock_run.side_effect = fake_subprocess(
        git_branch_valid=False,
        git_fetch_succeeds=True,
        git_exists_on_branch=False,
    )
    monkeypatch.setattr(
        sys, "argv", ["squawk-alembic", "--diff-branch", "origin/main", path]
    )
    assert main() == 0
    # git rev-parse (fail) + git fetch + git cat-file + alembic + squawk = 5 calls
    assert mock_run.call_count == 5
    assert mock_run.call_args_list[0][0][0][0] == "git"
    assert "fetch" in mock_run.call_args_list[1][0][0]
    assert "cat-file" in mock_run.call_args_list[2][0][0]


@patch("subprocess.run")
def test_origin_branch_shallow_fetch_fails(mock_run, repo, capsys, monkeypatch):
    """When both rev-parse and fetch fail, the hook should error."""
    path = write_migration(
        repo,
        "017_fetch_fail.py",
        """
        revision = 'ff001'
        down_revision = 'prev001'

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE foo (id int)")
        """,
    )
    mock_run.side_effect = fake_subprocess(
        git_branch_valid=False,
        git_fetch_succeeds=False,
    )
    monkeypatch.setattr(
        sys, "argv", ["squawk-alembic", "--diff-branch", "origin/main", path]
    )
    assert main() == 1
    # git rev-parse (fail) + git fetch (fail) = 2 calls
    assert mock_run.call_count == 2
    captured = capsys.readouterr()
    assert "not found in git" in captured.err


@patch("subprocess.run")
def test_non_origin_branch_no_fetch_attempted(mock_run, repo, capsys, monkeypatch):
    """Non-origin branches should not trigger a fetch attempt."""
    path = write_migration(
        repo,
        "018_no_fetch.py",
        """
        revision = 'nf001'
        down_revision = 'prev001'

        from alembic import op

        def upgrade():
            op.execute("CREATE TABLE foo (id int)")
        """,
    )
    mock_run.side_effect = fake_subprocess(git_branch_valid=False)
    monkeypatch.setattr(sys, "argv", ["squawk-alembic", "--diff-branch", "main", path])
    assert main() == 1
    # Only git rev-parse (fail), no fetch attempted
    assert mock_run.call_count == 1
    captured = capsys.readouterr()
    assert "not found in git" in captured.err
