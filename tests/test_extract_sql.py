"""Tests for SQL extraction from Alembic migration files."""

import textwrap

import pytest

from squawk_alembic.hook import extract_sql


@pytest.fixture()
def migration_file(tmp_path):
    """Write a migration file and return its path."""

    def _write(source):
        path = tmp_path / "migration.py"
        path.write_text(textwrap.dedent(source))
        return str(path)

    return _write


class TestDirectStringLiteral:
    def test_simple_execute(self, migration_file):
        path = migration_file("""
            from alembic import op

            def upgrade():
                op.execute("CREATE TABLE foo (id int)")
        """)
        assert extract_sql(path) == ["CREATE TABLE foo (id int)"]

    def test_triple_quoted_string(self, migration_file):
        path = migration_file('''
            from alembic import op

            def upgrade():
                op.execute("""
                    UPDATE organization_settings
                    SET enabled = true
                    WHERE org_id = 1
                """)
        ''')
        result = extract_sql(path)
        assert len(result) == 1
        assert "UPDATE organization_settings" in result[0]

    def test_implicit_string_concatenation(self, migration_file):
        path = migration_file("""
            from alembic import op

            def upgrade():
                op.execute(
                    "CREATE INDEX CONCURRENTLY ix_foo "
                    "ON bar (baz) "
                    "WHERE status = 'active'"
                )
        """)
        result = extract_sql(path)
        assert len(result) == 1
        assert "CREATE INDEX CONCURRENTLY ix_foo ON bar (baz)" in result[0]

    def test_multiple_execute_calls(self, migration_file):
        path = migration_file("""
            from alembic import op

            def upgrade():
                op.execute("SET lock_timeout = '10s'")
                op.execute("ALTER TABLE foo ADD COLUMN bar int")
        """)
        assert extract_sql(path) == [
            "SET lock_timeout = '10s'",
            "ALTER TABLE foo ADD COLUMN bar int",
        ]


class TestTextWrapper:
    def test_sa_text(self, migration_file):
        path = migration_file("""
            from alembic import op
            import sqlalchemy as sa

            def upgrade():
                op.execute(sa.text("CREATE TABLE foo (id int)"))
        """)
        assert extract_sql(path) == ["CREATE TABLE foo (id int)"]

    def test_bare_text(self, migration_file):
        path = migration_file("""
            from alembic import op
            from sqlalchemy import text

            def upgrade():
                op.execute(text("CREATE TABLE foo (id int)"))
        """)
        assert extract_sql(path) == ["CREATE TABLE foo (id int)"]


class TestOrmOpsIgnored:
    def test_add_column(self, migration_file):
        path = migration_file("""
            from alembic import op
            import sqlalchemy as sa

            def upgrade():
                op.add_column('users', sa.Column('email', sa.String(255)))
        """)
        assert extract_sql(path) == []

    def test_create_table(self, migration_file):
        path = migration_file("""
            from alembic import op
            import sqlalchemy as sa

            def upgrade():
                op.create_table(
                    'users',
                    sa.Column('id', sa.Integer, primary_key=True),
                    sa.Column('name', sa.String(255)),
                )
        """)
        assert extract_sql(path) == []

    def test_alter_column(self, migration_file):
        path = migration_file("""
            from alembic import op
            import sqlalchemy as sa

            def upgrade():
                op.alter_column(
                    'transactions', 'total_amount',
                    existing_type=sa.NUMERIC(precision=12, scale=2),
                    type_=sa.Numeric(precision=20, scale=2),
                )
        """)
        assert extract_sql(path) == []

    def test_mixed_orm_and_execute(self, migration_file):
        path = migration_file("""
            from alembic import op
            import sqlalchemy as sa

            def upgrade():
                op.add_column('users', sa.Column('email', sa.String(255)))
                op.execute("UPDATE users SET email = 'unknown' WHERE email IS NULL")
                op.alter_column('users', 'email', nullable=False)
        """)
        assert extract_sql(path) == [
            "UPDATE users SET email = 'unknown' WHERE email IS NULL",
        ]


class TestMergeMigration:
    def test_empty_upgrade(self, migration_file):
        path = migration_file("""
            revision = 'abc123'
            down_revision = ('def456', 'ghi789')
            branch_labels = None
            depends_on = None

            def upgrade():
                pass

            def downgrade():
                pass
        """)
        assert extract_sql(path) == []


class TestEdgeCases:
    def test_syntax_error(self, migration_file):
        path = migration_file("""
            this is not valid python {{{
        """)
        assert extract_sql(path) == []

    def test_no_op_execute(self, migration_file):
        path = migration_file("""
            from alembic import op

            def upgrade():
                pass
        """)
        assert extract_sql(path) == []

    def test_non_string_execute(self, migration_file):
        """op.execute() with a non-string argument should be skipped."""
        path = migration_file("""
            from alembic import op

            def upgrade():
                op.execute(some_variable)
        """)
        assert extract_sql(path) == []

    def test_fstring_execute(self, migration_file):
        """f-strings can't be evaluated statically, should be skipped."""
        path = migration_file("""
            from alembic import op

            table = "users"

            def upgrade():
                op.execute(f"DROP TABLE {table}")
        """)
        assert extract_sql(path) == []
