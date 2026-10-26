"""loan status changes

Revision ID: 67395e6ca3c6
Revises: 71bada3af11e
Create Date: 2026-10-26 11:45:14.462677

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "67395e6ca3c6"
down_revision: str | Sequence[str] | None = "71bada3af11e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
    CREATE TABLE loan_status_changes (
        id         bigserial   PRIMARY KEY,
        loan_id    text        NOT NULL REFERENCES loans (id),
        status     text        NOT NULL
            CONSTRAINT loan_status_changes_status_known
            CHECK (status IN ('active', 'completed', 'deleted')),
        changed_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    """)
    op.execute(
        "CREATE TRIGGER loan_status_changes_append_only"
        " BEFORE UPDATE OR DELETE ON loan_status_changes"
        " FOR EACH ROW EXECUTE FUNCTION forbid_change();"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE loan_status_changes;")
