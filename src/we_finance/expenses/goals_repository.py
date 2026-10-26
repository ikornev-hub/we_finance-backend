"""Цели накоплений в Postgres: цели, ручные взносы, накопительные счета, операции «Накопления»."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import psycopg2
from psycopg2 import errorcodes

from we_finance.expenses.db import Postgres
from we_finance.expenses.errors import ExpenseError
from we_finance.expenses.goals import Contribution, Goal, SavingsOperation


class Goals(Postgres):
    """Цели накоплений и ручные взносы."""

    def goals(self) -> list[Goal]:
        """Цели пользователя по порядку создания."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT id, name, target_amount, deadline, monthly_amount, initial_amount,"
                " start_date, loan_id FROM expense_goals WHERE user_id = %s ORDER BY created_at",
                (self._user_id,),
            )
            return [Goal(*row) for row in cur.fetchall()]

    def goal(self, goal_id: str) -> Goal | None:
        """Цель пользователя; нет — None."""
        return next((goal for goal in self.goals() if goal.id == goal_id), None)

    def save_goal(self, goal: Goal) -> None:
        """Новая цель или все поля существующей; имя занято — ExpenseError."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    "INSERT INTO expense_goals (id, user_id, name, target_amount, deadline,"
                    " monthly_amount, initial_amount, start_date, loan_id)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    " ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name,"
                    " target_amount = EXCLUDED.target_amount, deadline = EXCLUDED.deadline,"
                    " monthly_amount = EXCLUDED.monthly_amount,"
                    " initial_amount = EXCLUDED.initial_amount,"
                    " start_date = EXCLUDED.start_date, loan_id = EXCLUDED.loan_id",
                    (
                        goal.id,
                        self._user_id,
                        goal.name,
                        goal.target_amount,
                        goal.deadline,
                        goal.monthly_amount,
                        goal.initial_amount,
                        goal.start_date,
                        goal.loan_id,
                    ),
                )
        except psycopg2.IntegrityError as exc:
            if exc.pgcode != errorcodes.UNIQUE_VIOLATION:
                raise
            raise ExpenseError(f"Цель «{goal.name}» уже есть") from exc

    def delete_goal(self, goal_id: str) -> None:
        """Удалить цель с ручными взносами; привязанные накопительные счета — тоже."""
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM expense_accounts WHERE user_id = %s AND goal_id = %s",
                (self._user_id, goal_id),
            )
            cur.execute(
                "DELETE FROM expense_goals WHERE user_id = %s AND id = %s",
                (self._user_id, goal_id),
            )

    def add_contribution(
        self, goal_id: str, day: date, amount: Decimal, comment: str | None
    ) -> str:
        """Ручной взнос в цель: плюс — отложил, минус — снял."""
        contribution_id = uuid4().hex
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO expense_goal_contributions"
                " (id, user_id, goal_id, day, amount, comment)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (contribution_id, self._user_id, goal_id, day, amount, comment),
            )
        return contribution_id

    def manual_contributions(self) -> list[Contribution]:
        """Ручные взносы всех целей."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT goal_id, day, amount FROM expense_goal_contributions WHERE user_id = %s",
                (self._user_id,),
            )
            return [Contribution(*row) for row in cur.fetchall()]

    def savings_operations(self) -> list[SavingsOperation]:
        """Операции категории «Накопления» — переводы на накопительные счета и обратно."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT o.operated_at::date, o.amount, o.description FROM expense_operations o"
                " JOIN expense_categories c ON c.id = o.category_id"
                " WHERE o.user_id = %s AND c.system_code = 'savings'",
                (self._user_id,),
            )
            return [SavingsOperation(*row) for row in cur.fetchall()]

    def savings_accounts(self) -> dict[str, str]:
        """Накопительные счета: 4 последние цифры → id цели."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT number_tail, goal_id FROM expense_accounts"
                " WHERE user_id = %s AND kind = 'savings' AND number_tail IS NOT NULL",
                (self._user_id,),
            )
            return dict(cur.fetchall())
