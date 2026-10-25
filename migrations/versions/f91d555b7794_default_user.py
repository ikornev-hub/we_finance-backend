"""default user

Revision ID: f91d555b7794
Revises: 72b30a9f56e0
Create Date: 2026-10-25 19:19:48.223644

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f91d555b7794"
down_revision: str | Sequence[str] | None = "72b30a9f56e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Пока нет входа, API работает от имени u1 — он должен существовать.
    op.execute("INSERT INTO users (id, login) VALUES ('u1', 'owner') ON CONFLICT DO NOTHING;")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM users WHERE id = 'u1';")
