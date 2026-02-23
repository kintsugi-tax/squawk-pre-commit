"""Tests for CONCURRENTLY outside autocommit_block detection."""

import textwrap

import pytest

from squawk_alembic.hook import check_autocommit_blocks


@pytest.fixture()
def migration_file(tmp_path):
    """Write a migration file and return its path."""

    def _write(source):
        path = tmp_path / "migration.py"
        path.write_text(textwrap.dedent(source))
        return str(path)

    return _write


# --- op.execute with CONCURRENTLY inside autocommit ---


def test_create_index_execute_in_autocommit(migration_file):
    path = migration_file("""
        from alembic import op

        def upgrade():
            with op.get_context().autocommit_block():
                op.execute("CREATE INDEX CONCURRENTLY ix_foo ON bar (baz)")
    """)
    assert check_autocommit_blocks(path) == []


def test_drop_index_execute_in_autocommit(migration_file):
    path = migration_file("""
        from alembic import op

        def upgrade():
            with op.get_context().autocommit_block():
                op.execute("DROP INDEX CONCURRENTLY ix_foo")
    """)
    assert check_autocommit_blocks(path) == []


def test_multiple_execute_ops_in_autocommit(migration_file):
    path = migration_file("""
        from alembic import op

        def upgrade():
            with op.get_context().autocommit_block():
                op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_old")
                op.execute("CREATE INDEX CONCURRENTLY ix_new ON bar (baz)")
    """)
    assert check_autocommit_blocks(path) == []


# --- op.execute with CONCURRENTLY outside autocommit ---


def test_create_index_execute_no_autocommit(migration_file):
    path = migration_file("""
        from alembic import op

        def upgrade():
            op.execute("CREATE INDEX CONCURRENTLY ix_foo ON bar (baz)")
    """)
    assert len(check_autocommit_blocks(path)) == 1


def test_drop_index_execute_no_autocommit(migration_file):
    path = migration_file("""
        from alembic import op

        def upgrade():
            op.execute("DROP INDEX CONCURRENTLY ix_foo")
    """)
    assert len(check_autocommit_blocks(path)) == 1


def test_execute_case_insensitive(migration_file):
    path = migration_file("""
        from alembic import op

        def upgrade():
            op.execute("create index concurrently ix_foo on bar (baz)")
    """)
    assert len(check_autocommit_blocks(path)) == 1


def test_execute_mixed_inside_and_outside(migration_file):
    """One op inside autocommit, one outside. Only the outside one should warn."""
    path = migration_file("""
        from alembic import op

        def upgrade():
            op.execute("CREATE INDEX CONCURRENTLY ix_bad ON bar (baz)")
            with op.get_context().autocommit_block():
                op.execute("CREATE INDEX CONCURRENTLY ix_good ON bar (qux)")
    """)
    assert len(check_autocommit_blocks(path)) == 1


def test_execute_warning_includes_line_number(migration_file):
    path = migration_file("""
        from alembic import op

        def upgrade():
            op.execute("CREATE INDEX CONCURRENTLY ix_foo ON bar (baz)")
    """)
    warnings = check_autocommit_blocks(path)
    assert len(warnings) == 1
    assert isinstance(warnings[0], int)


# --- op.create_index / op.drop_index with postgresql_concurrently ---


def test_create_index_concurrent_inside_autocommit(migration_file):
    path = migration_file("""
        from alembic import op

        def upgrade():
            with op.get_context().autocommit_block():
                op.create_index("ix_foo", "bar", ["baz"], postgresql_concurrently=True)
    """)
    assert check_autocommit_blocks(path) == []


def test_create_index_concurrent_outside_autocommit(migration_file):
    path = migration_file("""
        from alembic import op

        def upgrade():
            op.create_index("ix_foo", "bar", ["baz"], postgresql_concurrently=True)
    """)
    assert len(check_autocommit_blocks(path)) == 1


def test_create_index_without_concurrent_kwarg(migration_file):
    path = migration_file("""
        from alembic import op

        def upgrade():
            op.create_index("ix_foo", "bar", ["baz"])
    """)
    assert check_autocommit_blocks(path) == []


def test_drop_index_concurrent_outside_autocommit(migration_file):
    path = migration_file("""
        from alembic import op

        def upgrade():
            op.drop_index("ix_foo", postgresql_concurrently=True)
    """)
    assert len(check_autocommit_blocks(path)) == 1


def test_create_index_concurrent_mixed(migration_file):
    """Only ops outside autocommit should warn."""
    path = migration_file("""
        from alembic import op

        def upgrade():
            op.create_index("ix_bad", "bar", ["baz"], postgresql_concurrently=True)
            with op.get_context().autocommit_block():
                op.create_index("ix_good", "bar", ["qux"], postgresql_concurrently=True)
    """)
    assert len(check_autocommit_blocks(path)) == 1


# --- No false positives ---


def test_non_concurrent_index(migration_file):
    path = migration_file("""
        from alembic import op

        def upgrade():
            op.execute("CREATE INDEX ix_foo ON bar (baz)")
    """)
    assert check_autocommit_blocks(path) == []


def test_no_execute_calls(migration_file):
    path = migration_file("""
        from alembic import op
        import sqlalchemy as sa

        def upgrade():
            op.add_column('users', sa.Column('email', sa.String(255)))
    """)
    assert check_autocommit_blocks(path) == []


def test_concurrently_in_non_concurrent_string(migration_file):
    """Only flag actual CONCURRENTLY SQL, not unrelated strings."""
    path = migration_file("""
        from alembic import op

        def upgrade():
            op.execute("SET lock_timeout = '10s'")
    """)
    assert check_autocommit_blocks(path) == []


def test_syntax_error(migration_file):
    path = migration_file("""
        this is not valid python {{{
    """)
    assert check_autocommit_blocks(path) == []
