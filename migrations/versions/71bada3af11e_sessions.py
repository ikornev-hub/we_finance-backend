"""sessions

Revision ID: 71bada3af11e
Revises: da9748ac928e
Create Date: 2026-10-26 11:08:20.395273

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "71bada3af11e"
down_revision: str | Sequence[str] | None = "da9748ac928e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
    CREATE TABLE sessions (
        token_hash text        PRIMARY KEY,
        user_id    text        NOT NULL REFERENCES users (id),
        created_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL DEFAULT now() + interval '30 days'
    );
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE sessions;")
