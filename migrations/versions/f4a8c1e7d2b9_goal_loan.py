"""savings goal can close a loan

Revision ID: f4a8c1e7d2b9
Revises: e2c7a9d4b5f1
Create Date: 2026-10-27 15:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a8c1e7d2b9"
down_revision: str | Sequence[str] | None = "e2c7a9d4b5f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Цель «закрыть кредит к дате»: взносы — ЧДП по этому кредиту."""
    op.execute("ALTER TABLE expense_goals ADD COLUMN loan_id text REFERENCES loans (id);")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE expense_goals DROP COLUMN loan_id;")
