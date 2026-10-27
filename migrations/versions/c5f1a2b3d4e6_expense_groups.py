"""expense groups above categories

Revision ID: c5f1a2b3d4e6
Revises: b3d7e1a9c4f2
Create Date: 2026-10-26 21:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5f1a2b3d4e6"
down_revision: str | Sequence[str] | None = "b3d7e1a9c4f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Группы трат: обязательные, управляемые, неуправляемые, покупки; у категории — группа."""
    op.execute("""
    CREATE TABLE expense_groups (
        id            text    PRIMARY KEY,
        user_id       text    NOT NULL REFERENCES users (id),
        code          text    NOT NULL
            CONSTRAINT expense_groups_code_known
            CHECK (code IN ('mandatory', 'managed', 'unmanaged', 'purchases')),
        name          text    NOT NULL
            CONSTRAINT expense_groups_name_not_empty
            CHECK (name <> ''),
        target_share  numeric
            CONSTRAINT expense_groups_share_valid
            CHECK (target_share BETWEEN 0 AND 1),
        target_amount numeric
            CONSTRAINT expense_groups_amount_valid
            CHECK (target_amount >= 0 AND scale(target_amount) <= 2),
        CONSTRAINT expense_groups_one_limit
            CHECK (target_share IS NULL OR target_amount IS NULL),
        CONSTRAINT expense_groups_unique_code
            UNIQUE (user_id, code)
    );

    ALTER TABLE expense_categories
        ADD COLUMN group_id text REFERENCES expense_groups (id);
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("""
    ALTER TABLE expense_categories DROP COLUMN group_id;
    DROP TABLE expense_groups;
    """)
