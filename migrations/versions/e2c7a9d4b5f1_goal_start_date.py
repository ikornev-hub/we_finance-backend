"""savings goal start date

Revision ID: e2c7a9d4b5f1
Revises: d8a4b6c2e1f3
Create Date: 2026-10-27 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2c7a9d4b5f1"
down_revision: str | Sequence[str] | None = "d8a4b6c2e1f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """С какого числа начать копить: до этого месяца цель денег не берёт."""
    op.execute("ALTER TABLE expense_goals ADD COLUMN start_date date;")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE expense_goals DROP COLUMN start_date;")
