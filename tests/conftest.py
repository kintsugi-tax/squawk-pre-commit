"""Shared test fixtures."""

import textwrap
from types import SimpleNamespace

from pytest import fixture


@fixture()
def repo(tmp_path, monkeypatch):
    """Set up a fake repo with alembic config and a versions directory."""
    monkeypatch.chdir(tmp_path)
    versions = tmp_path / "migrations" / "versions"
    versions.mkdir(parents=True)
    (tmp_path / "alembic.ini").write_text("[alembic]\nscript_location = ./migrations\n")
    return tmp_path


def make_result(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def write_migration(repo, filename, source):
    path = repo / "migrations" / "versions" / filename
    path.write_text(textwrap.dedent(source))
    return f"migrations/versions/{filename}"


def fake_subprocess(
    alembic_result=None,
    squawk_result=None,
    git_exists_on_branch=False,
    git_branch_valid=True,
    git_fetch_succeeds=False,
):
    """Return a side_effect function that dispatches based on the command."""
    alembic_res = alembic_result or make_result(stdout="CREATE TABLE foo (id int);\n")
    squawk_res = squawk_result or make_result()

    def side_effect(cmd, **kwargs):
        if cmd[0] == "git":
            if "rev-parse" in cmd:
                return make_result(returncode=0 if git_branch_valid else 1)
            if "fetch" in cmd:
                return make_result(returncode=0 if git_fetch_succeeds else 1)
            if "cat-file" in cmd:
                return make_result(returncode=0 if git_exists_on_branch else 1)
            return make_result(returncode=1)
        if cmd[0] == "alembic":
            return alembic_res
        if cmd[0] == "squawk":
            return squawk_res
        raise ValueError(f"unexpected command: {cmd}")

    return side_effect
