"""append only loan history

Revision ID: 1f2dfb76340d
Revises: f91d555b7794
Create Date: 2026-10-25 20:24:23.680358

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1f2dfb76340d"
down_revision: str | Sequence[str] | None = "f91d555b7794"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("loans", "rate_periods", "payment_day_changes", "prepayments")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
    CREATE FUNCTION forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'Таблица % только для добавления: % запрещён', TG_TABLE_NAME, TG_OP;
    END;
    $$;
    """)
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_change();"
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table in TABLES:
        op.execute(f"DROP TRIGGER {table}_append_only ON {table};")
    op.execute("DROP FUNCTION forbid_change();")
