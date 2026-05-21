"""Shared test fixtures."""

from pytest import fixture


@fixture()
def repo(tmp_path, monkeypatch):
    """Set up a fake repo with alembic config and a versions directory."""
    monkeypatch.chdir(tmp_path)
    versions = tmp_path / "migrations" / "versions"
    versions.mkdir(parents=True)
    (tmp_path / "alembic.ini").write_text("[alembic]\nscript_location = ./migrations\n")
    return tmp_path
