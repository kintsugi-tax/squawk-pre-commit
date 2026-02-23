"""Tests for extract_revision_info from Alembic migration files."""

import textwrap

import pytest

from squawk_alembic.hook import extract_revision_info


@pytest.fixture()
def migration_file(tmp_path):
    """Write a migration file and return its path."""

    def _write(source):
        path = tmp_path / "migration.py"
        path.write_text(textwrap.dedent(source))
        return str(path)

    return _write


def test_standard_migration(migration_file):
    path = migration_file("""
        revision = 'abc123'
        down_revision = 'def456'
        branch_labels = None
        depends_on = None

        def upgrade():
            pass
    """)
    info = extract_revision_info(path)
    assert info is not None
    assert info.revision == "abc123"
    assert info.down_revision == "def456"
    assert info.is_merge is False


def test_first_migration_down_revision_is_none(migration_file):
    path = migration_file("""
        revision = 'abc123'
        down_revision = None
        branch_labels = None
        depends_on = None

        def upgrade():
            pass
    """)
    info = extract_revision_info(path)
    assert info is not None
    assert info.revision == "abc123"
    assert info.down_revision is None
    assert info.is_merge is False


def test_merge_migration_tuple_down_revision(migration_file):
    path = migration_file("""
        revision = 'merge001'
        down_revision = ('abc123', 'def456')
        branch_labels = None
        depends_on = None

        def upgrade():
            pass
    """)
    info = extract_revision_info(path)
    assert info is not None
    assert info.revision == "merge001"
    assert info.down_revision == ("abc123", "def456")
    assert info.is_merge is True


def test_syntax_error_returns_none(migration_file):
    path = migration_file("""
        this is not valid python {{{
    """)
    assert extract_revision_info(path) is None


def test_missing_revision_variable_returns_none(migration_file):
    path = migration_file("""
        down_revision = 'def456'

        def upgrade():
            pass
    """)
    assert extract_revision_info(path) is None
