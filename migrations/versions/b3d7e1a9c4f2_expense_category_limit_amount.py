"""expense category limit as amount

Revision ID: b3d7e1a9c4f2
Revises: 4909cf1ede18
Create Date: 2026-10-26 18:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d7e1a9c4f2"
down_revision: str | Sequence[str] | None = "4909cf1ede18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Граница категории — либо доля располагаемого, либо сумма в рублях."""
    op.execute("""
    ALTER TABLE expense_categories
        ADD COLUMN target_amount numeric
            CONSTRAINT expense_categories_amount_valid
            CHECK (target_amount >= 0 AND scale(target_amount) <= 2),
        ADD CONSTRAINT expense_categories_one_limit
            CHECK (target_share IS NULL OR target_amount IS NULL);
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("""
    ALTER TABLE expense_categories
        DROP CONSTRAINT expense_categories_one_limit,
        DROP COLUMN target_amount;
    """)
