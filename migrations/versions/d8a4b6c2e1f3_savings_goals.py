"""savings goals

Revision ID: d8a4b6c2e1f3
Revises: c5f1a2b3d4e6
Create Date: 2026-10-26 22:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8a4b6c2e1f3"
down_revision: str | Sequence[str] | None = "c5f1a2b3d4e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Цели накоплений, ручные взносы, накопительный счёт у цели."""
    op.execute("""
    CREATE TABLE expense_goals (
        id             text    PRIMARY KEY,
        user_id        text    NOT NULL REFERENCES users (id),
        name           text    NOT NULL
            CONSTRAINT expense_goals_name_not_empty CHECK (name <> ''),
        target_amount  numeric NOT NULL
            CONSTRAINT expense_goals_target_positive
            CHECK (target_amount > 0 AND scale(target_amount) <= 2),
        deadline       date,
        monthly_amount numeric
            CONSTRAINT expense_goals_monthly_valid
            CHECK (monthly_amount > 0 AND scale(monthly_amount) <= 2),
        initial_amount numeric NOT NULL DEFAULT 0
            CONSTRAINT expense_goals_initial_valid
            CHECK (initial_amount >= 0 AND scale(initial_amount) <= 2),
        created_at     timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT expense_goals_deadline_or_monthly
            CHECK (deadline IS NOT NULL OR monthly_amount IS NOT NULL),
        CONSTRAINT expense_goals_unique_name UNIQUE (user_id, name)
    );

    CREATE TABLE expense_goal_contributions (
        id         text    PRIMARY KEY,
        user_id    text    NOT NULL REFERENCES users (id),
        goal_id    text    NOT NULL REFERENCES expense_goals (id) ON DELETE CASCADE,
        day        date    NOT NULL,
        amount     numeric NOT NULL
            CONSTRAINT expense_goal_contributions_amount_valid
            CHECK (amount <> 0 AND scale(amount) <= 2),
        comment    text,
        created_at timestamptz NOT NULL DEFAULT now()
    );

    ALTER TABLE expense_accounts
        DROP CONSTRAINT expense_accounts_kind_known,
        ADD CONSTRAINT expense_accounts_kind_known CHECK (kind IN ('own', 'credit', 'savings')),
        ADD COLUMN goal_id text REFERENCES expense_goals (id),
        ADD CONSTRAINT expense_accounts_savings_has_goal
            CHECK ((kind = 'savings') = (goal_id IS NOT NULL));
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("""
    DELETE FROM expense_accounts WHERE kind = 'savings';
    ALTER TABLE expense_accounts
        DROP CONSTRAINT expense_accounts_savings_has_goal,
        DROP COLUMN goal_id,
        DROP CONSTRAINT expense_accounts_kind_known,
        ADD CONSTRAINT expense_accounts_kind_known CHECK (kind IN ('own', 'credit'));
    DROP TABLE expense_goal_contributions;
    DROP TABLE expense_goals;
    """)
