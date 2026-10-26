"""salary tables

Revision ID: edaaf630183d
Revises: 1f2dfb76340d
Create Date: 2026-10-26 09:30:56.547480

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "edaaf630183d"
down_revision: str | Sequence[str] | None = "1f2dfb76340d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE TABLE salary_profiles (
            user_id     text        PRIMARY KEY REFERENCES users (id),
            stage_start date        NOT NULL,
            updated_at  timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE salary_terms (
            user_id      text    NOT NULL REFERENCES salary_profiles (user_id),
            start_date   date    NOT NULL,
            salary       numeric NOT NULL
                CONSTRAINT salary_terms_salary_positive CHECK (salary > 0)
                CONSTRAINT salary_terms_salary_cents CHECK (scale(salary) <= 2),
            meal_per_day numeric NOT NULL
                CONSTRAINT salary_terms_meal_not_negative CHECK (meal_per_day >= 0)
                CONSTRAINT salary_terms_meal_cents CHECK (scale(meal_per_day) <= 2),
            PRIMARY KEY (user_id, start_date)
        );

        CREATE TABLE absences (
            user_id    text NOT NULL REFERENCES salary_profiles (user_id),
            kind       text NOT NULL
                CONSTRAINT absences_kind_known CHECK (kind IN ('vacation', 'sick', 'unpaid')),
            start_date date NOT NULL,
            end_date   date NOT NULL,
            CONSTRAINT absences_end_not_before_start CHECK (end_date >= start_date),
            PRIMARY KEY (user_id, start_date)
        );

        CREATE TABLE salary_history (
            user_id       text    NOT NULL REFERENCES salary_profiles (user_id),
            year          integer NOT NULL
                CONSTRAINT salary_history_year_valid CHECK (year >= 2000),
            month         integer NOT NULL
                CONSTRAINT salary_history_month_valid CHECK (month BETWEEN 1 AND 12),
            salary        numeric NOT NULL
                CONSTRAINT salary_history_salary_not_negative CHECK (salary >= 0),
            vacation_pay  numeric NOT NULL DEFAULT 0
                CONSTRAINT salary_history_vacation_not_negative CHECK (vacation_pay >= 0),
            excluded_days integer NOT NULL DEFAULT 0
                CONSTRAINT salary_history_excluded_days_valid
                CHECK (excluded_days BETWEEN 0 AND 31),
            PRIMARY KEY (user_id, year, month)
        );
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE salary_history, absences, salary_terms, salary_profiles;")
