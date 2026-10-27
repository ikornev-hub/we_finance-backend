"""statement closing balance

Revision ID: a1b2c3d4e5f6
Revises: f4a8c1e7d2b9
Create Date: 2026-10-27 18:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f4a8c1e7d2b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Остаток на счёте на конец периода выписки: от него — остаток на любой день."""
    op.execute("ALTER TABLE expense_imports ADD COLUMN closing_balance numeric;")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE expense_imports DROP COLUMN closing_balance;")
