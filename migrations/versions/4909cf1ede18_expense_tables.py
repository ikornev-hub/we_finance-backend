"""expense tables

Revision ID: 4909cf1ede18
Revises: 67395e6ca3c6
Create Date: 2026-10-26 14:51:26.136590

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4909cf1ede18"
down_revision: str | Sequence[str] | None = "67395e6ca3c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
    CREATE TABLE expense_categories (
        id           text    PRIMARY KEY,
        user_id      text    NOT NULL REFERENCES users (id),
        parent_id    text    REFERENCES expense_categories (id),
        name         text    NOT NULL
            CONSTRAINT expense_categories_name_not_empty
            CHECK (name <> ''),
        kind         text    NOT NULL DEFAULT 'expense'
            CONSTRAINT expense_categories_kind_known
            CHECK (kind IN ('expense', 'income', 'neutral')),
        system_code  text,
        target_share numeric
            CONSTRAINT expense_categories_share_valid
            CHECK (target_share BETWEEN 0 AND 1),
        CONSTRAINT expense_categories_unique_name
            UNIQUE NULLS NOT DISTINCT (user_id, parent_id, name),
        CONSTRAINT expense_categories_unique_system
            UNIQUE (user_id, system_code)
    );

    CREATE TABLE expense_accounts (
        id              text    PRIMARY KEY,
        user_id         text    NOT NULL REFERENCES users (id),
        bank            text    NOT NULL,
        number_tail     text,
        phone           text,
        kind            text    NOT NULL
            CONSTRAINT expense_accounts_kind_known
            CHECK (kind IN ('own', 'credit')),
        loan_id         text    REFERENCES loans (id),
        opening_balance numeric NOT NULL DEFAULT 0,
        name            text    NOT NULL,
        CONSTRAINT expense_accounts_number_or_phone
            CHECK (number_tail IS NOT NULL OR phone IS NOT NULL),
        CONSTRAINT expense_accounts_credit_has_loan
            CHECK ((kind = 'credit') = (loan_id IS NOT NULL))
    );

    CREATE TABLE expense_rules (
        id          text        PRIMARY KEY,
        user_id     text        NOT NULL REFERENCES users (id),
        match_kind  text        NOT NULL
            CONSTRAINT expense_rules_match_known
            CHECK (match_kind IN ('counterparty', 'merchant', 'mcc')),
        pattern     text        NOT NULL
            CONSTRAINT expense_rules_pattern_not_empty
            CHECK (pattern <> ''),
        amount      numeric,
        category_id text        NOT NULL REFERENCES expense_categories (id),
        created_at  timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE expense_imports (
        id          text        PRIMARY KEY,
        user_id     text        NOT NULL REFERENCES users (id),
        bank        text        NOT NULL,
        file_name   text        NOT NULL,
        period_from date,
        period_to   date,
        loaded_at   timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE expense_operations (
        id                text      PRIMARY KEY,
        user_id           text      NOT NULL REFERENCES users (id),
        import_id         text      NOT NULL REFERENCES expense_imports (id),
        bank              text      NOT NULL,
        bank_operation_id text      NOT NULL,
        operated_at       timestamp NOT NULL,
        amount            numeric   NOT NULL
            CONSTRAINT expense_operations_amount_cents
            CHECK (scale(amount) <= 2),
        description       text      NOT NULL,
        merchant          text,
        mcc               text,
        counterparty      text,
        type              text      NOT NULL,
        category_id       text      REFERENCES expense_categories (id),
        category_source   text      NOT NULL DEFAULT 'default'
            CONSTRAINT expense_operations_source_known
            CHECK (category_source IN ('rule', 'user', 'default')),
        pair_id           text,
        CONSTRAINT expense_operations_unique_bank_id UNIQUE (user_id, bank, bank_operation_id)
    );
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "DROP TABLE expense_operations, expense_imports, expense_rules,"
        " expense_accounts, expense_categories;"
    )
