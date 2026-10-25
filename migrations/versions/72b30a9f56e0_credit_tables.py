"""credit tables

Revision ID: 72b30a9f56e0
Revises:
Create Date: 2026-10-25 18:12:31.127619

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "72b30a9f56e0"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
    CREATE TABLE users (
    id text NOT NULL PRIMARY KEY,
    login text NOT NULL
        CONSTRAINT users_login_unique UNIQUE
        CONSTRAINT users_login_not_empty CHECK (login <> ''),
    created_at timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE loans (
    id text PRIMARY KEY,
    user_id text NOT NULL REFERENCES users (id),
    name text NOT NULL CONSTRAINT loans_name_length CHECK (
        char_length(name) BETWEEN 1 AND 100
    ),
    principal numeric NOT NULL
        CONSTRAINT loans_principal_positive CHECK (principal > 0)
        CONSTRAINT loans_principal_cents CHECK (scale (principal) <= 2),
    payment numeric NOT NULL
        CONSTRAINT loans_payment_positive CHECK (payment > 0)
        CONSTRAINT loans_payment_cents CHECK (scale (payment) <= 2),
    months integer NOT NULL CONSTRAINT loans_months_positive CHECK (months >= 1),
    issue_date date NOT NULL,
    first_payment_date date NOT NULL,
    day_count text NOT NULL DEFAULT 'actual'
        CONSTRAINT loans_day_count_known CHECK (day_count IN ('actual', '365')),
    weekend_shift boolean NOT NULL DEFAULT true,
    monthly_fee numeric NOT NULL DEFAULT 0.00
        CONSTRAINT loans_monthly_fee_not_negative CHECK (monthly_fee >= 0)
        CONSTRAINT loans_monthly_fee_cents CHECK (scale (monthly_fee) <= 2),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT loans_first_payment_after_issue CHECK (
        first_payment_date > issue_date
    )
    );

    CREATE TABLE rate_periods (
    loan_id text NOT NULL REFERENCES loans (id),
    start_date date NOT NULL,
    annual_rate numeric NOT NULL
        CONSTRAINT rate_periods_annual_rate_not_negative CHECK (annual_rate >= 0),
    PRIMARY KEY (loan_id, start_date)
    );

    CREATE TABLE payment_day_changes (
    loan_id text NOT NULL REFERENCES loans (id),
    start_date date NOT NULL,
    day integer NOT NULL
        CONSTRAINT payment_day_changes_day_in_month CHECK (day BETWEEN 1 AND 31),
    PRIMARY KEY (loan_id, start_date)
    );

    CREATE TABLE prepayments (
    id text PRIMARY KEY,
    loan_id text NOT NULL REFERENCES loans (id),
    prepayment_date date NOT NULL,
    amount numeric NOT NULL
        CONSTRAINT prepayments_amount_positive CHECK (amount > 0)
        CONSTRAINT prepayments_amount_cents CHECK (scale (amount) <= 2),
    mode text NOT NULL
        CONSTRAINT prepayments_mode_known CHECK (mode IN ('reduce_term', 'reduce_payment')),
    created_at timestamptz NOT NULL DEFAULT now()
    );
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE prepayments, payment_day_changes, rate_periods, loans, users;")
