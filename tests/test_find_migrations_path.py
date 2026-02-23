"""Tests for alembic.ini auto-detection."""

from pytest import fixture

from squawk_alembic.hook import find_migrations_path


@fixture()
def repo(tmp_path, monkeypatch):
    """Set up a fake repo directory and chdir into it."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_standard_layout(repo):
    (repo / "migrations" / "versions").mkdir(parents=True)
    (repo / "alembic.ini").write_text("[alembic]\nscript_location = ./migrations\n")
    result = find_migrations_path()
    assert result is not None
    assert result.name == "versions"
    assert result.parent.name == "migrations"


def test_nested_layout(repo):
    (repo / "backend" / "migrations" / "versions").mkdir(parents=True)
    (repo / "alembic.ini").write_text(
        "[alembic]\nscript_location = ./backend/migrations\n"
    )
    result = find_migrations_path()
    assert result is not None
    assert result.name == "versions"
    assert result.parent.name == "migrations"


def test_no_dot_slash_prefix(repo):
    (repo / "migrations" / "versions").mkdir(parents=True)
    (repo / "alembic.ini").write_text("[alembic]\nscript_location = migrations\n")
    assert find_migrations_path() is not None


def test_no_alembic_ini(repo):
    assert find_migrations_path() is None


def test_missing_script_location(repo):
    (repo / "alembic.ini").write_text("[alembic]\n")
    assert find_migrations_path() is None


def test_missing_alembic_section(repo):
    (repo / "alembic.ini").write_text("[other]\nkey = value\n")
    assert find_migrations_path() is None


def test_versions_dir_missing(repo):
    (repo / "migrations").mkdir()
    (repo / "alembic.ini").write_text("[alembic]\nscript_location = ./migrations\n")
    assert find_migrations_path() is None
