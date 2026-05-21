"""Tests for alembic.ini auto-detection."""

from pytest import fixture

from squawk_alembic.hook import find_migrations_path


@fixture()
def bare_repo(tmp_path, monkeypatch):
    """Set up a bare repo directory (no versions dir) and chdir into it."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_standard_layout(bare_repo):
    (bare_repo / "migrations" / "versions").mkdir(parents=True)
    (bare_repo / "alembic.ini").write_text(
        "[alembic]\nscript_location = ./migrations\n"
    )
    result = find_migrations_path()
    assert result is not None
    assert result.name == "versions"
    assert result.parent.name == "migrations"


def test_nested_layout(bare_repo):
    (bare_repo / "backend" / "migrations" / "versions").mkdir(parents=True)
    (bare_repo / "alembic.ini").write_text(
        "[alembic]\nscript_location = ./backend/migrations\n"
    )
    result = find_migrations_path()
    assert result is not None
    assert result.name == "versions"
    assert result.parent.name == "migrations"


def test_no_dot_slash_prefix(bare_repo):
    (bare_repo / "migrations" / "versions").mkdir(parents=True)
    (bare_repo / "alembic.ini").write_text("[alembic]\nscript_location = migrations\n")
    assert find_migrations_path() is not None


def test_no_alembic_ini(bare_repo):
    assert find_migrations_path() is None


def test_missing_script_location(bare_repo):
    (bare_repo / "alembic.ini").write_text("[alembic]\n")
    assert find_migrations_path() is None


def test_missing_alembic_section(bare_repo):
    (bare_repo / "alembic.ini").write_text("[other]\nkey = value\n")
    assert find_migrations_path() is None


def test_versions_dir_missing(bare_repo):
    (bare_repo / "migrations").mkdir()
    (bare_repo / "alembic.ini").write_text(
        "[alembic]\nscript_location = ./migrations\n"
    )
    assert find_migrations_path() is None
