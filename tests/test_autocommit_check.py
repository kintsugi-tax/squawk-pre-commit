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


class TestConcurrentlyInsideAutocommitBlock:
    def test_create_index_in_autocommit(self, migration_file):
        path = migration_file("""
            from alembic import op

            def upgrade():
                with op.get_context().autocommit_block():
                    op.execute("CREATE INDEX CONCURRENTLY ix_foo ON bar (baz)")
        """)
        assert check_autocommit_blocks(path) == []

    def test_drop_index_in_autocommit(self, migration_file):
        path = migration_file("""
            from alembic import op

            def upgrade():
                with op.get_context().autocommit_block():
                    op.execute("DROP INDEX CONCURRENTLY ix_foo")
        """)
        assert check_autocommit_blocks(path) == []

    def test_multiple_ops_in_autocommit(self, migration_file):
        path = migration_file("""
            from alembic import op

            def upgrade():
                with op.get_context().autocommit_block():
                    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_old")
                    op.execute("CREATE INDEX CONCURRENTLY ix_new ON bar (baz)")
        """)
        assert check_autocommit_blocks(path) == []


class TestConcurrentlyOutsideAutocommitBlock:
    def test_create_index_no_autocommit(self, migration_file):
        path = migration_file("""
            from alembic import op

            def upgrade():
                op.execute("CREATE INDEX CONCURRENTLY ix_foo ON bar (baz)")
        """)
        warnings = check_autocommit_blocks(path)
        assert len(warnings) == 1

    def test_drop_index_no_autocommit(self, migration_file):
        path = migration_file("""
            from alembic import op

            def upgrade():
                op.execute("DROP INDEX CONCURRENTLY ix_foo")
        """)
        warnings = check_autocommit_blocks(path)
        assert len(warnings) == 1

    def test_case_insensitive(self, migration_file):
        path = migration_file("""
            from alembic import op

            def upgrade():
                op.execute("create index concurrently ix_foo on bar (baz)")
        """)
        warnings = check_autocommit_blocks(path)
        assert len(warnings) == 1

    def test_mixed_inside_and_outside(self, migration_file):
        """One op inside autocommit, one outside. Only the outside one should warn."""
        path = migration_file("""
            from alembic import op

            def upgrade():
                op.execute("CREATE INDEX CONCURRENTLY ix_bad ON bar (baz)")
                with op.get_context().autocommit_block():
                    op.execute("CREATE INDEX CONCURRENTLY ix_good ON bar (qux)")
        """)
        warnings = check_autocommit_blocks(path)
        assert len(warnings) == 1

    def test_warning_includes_line_number(self, migration_file):
        path = migration_file("""
            from alembic import op

            def upgrade():
                op.execute("CREATE INDEX CONCURRENTLY ix_foo ON bar (baz)")
        """)
        warnings = check_autocommit_blocks(path)
        assert len(warnings) == 1
        assert isinstance(warnings[0], int)


class TestNoFalsePositives:
    def test_non_concurrent_index(self, migration_file):
        path = migration_file("""
            from alembic import op

            def upgrade():
                op.execute("CREATE INDEX ix_foo ON bar (baz)")
        """)
        assert check_autocommit_blocks(path) == []

    def test_no_execute_calls(self, migration_file):
        path = migration_file("""
            from alembic import op
            import sqlalchemy as sa

            def upgrade():
                op.add_column('users', sa.Column('email', sa.String(255)))
        """)
        assert check_autocommit_blocks(path) == []

    def test_concurrently_in_comment_like_string(self, migration_file):
        """Only flag actual CONCURRENTLY SQL, not unrelated strings."""
        path = migration_file("""
            from alembic import op

            def upgrade():
                op.execute("SET lock_timeout = '10s'")
        """)
        assert check_autocommit_blocks(path) == []

    def test_syntax_error(self, migration_file):
        path = migration_file("""
            this is not valid python {{{
        """)
        assert check_autocommit_blocks(path) == []
