"""user password hash

Revision ID: da9748ac928e
Revises: edaaf630183d
Create Date: 2026-10-26 10:44:20.993797

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "da9748ac928e"
down_revision: str | Sequence[str] | None = "edaaf630183d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Пусто = вход не настроен: пароль задаёт владелец командой we-finance set-password.
    op.execute("ALTER TABLE users ADD COLUMN password_hash text;")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE users DROP COLUMN password_hash;")
