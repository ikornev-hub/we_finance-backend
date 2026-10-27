"""Остаток на счёте: якорь из шапки выписки и движение по дням."""

from datetime import date
from decimal import Decimal

from we_finance.expenses.db import Postgres


class Balances(Postgres):
    """Остаток на конец последней выписки и сальдо операций по дням."""

    def balance_anchor(self) -> tuple[date, Decimal] | None:
        """(последний день выписки, остаток на счёте в этот день) — самая свежая выписка."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT period_to, closing_balance FROM expense_imports"
                " WHERE user_id = %s AND closing_balance IS NOT NULL AND period_to IS NOT NULL"
                " ORDER BY period_to DESC, loaded_at DESC LIMIT 1",
                (self._user_id,),
            )
            row = cur.fetchone()
        return (row[0], row[1]) if row else None

    def daily_net(self, start: date, end: date) -> dict[date, Decimal]:
        """Сальдо операций по дням в [start, end]: пришло − ушло."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT operated_at::date, sum(amount) FROM expense_operations"
                " WHERE user_id = %s AND operated_at::date BETWEEN %s AND %s GROUP BY 1",
                (self._user_id, start, end),
            )
            return dict(cur.fetchall())

    def statement_until(self) -> date | None:
        """По какой день есть выписка: конец периода самой свежей."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT max(period_to) FROM expense_imports WHERE user_id = %s", (self._user_id,)
            )
            row = cur.fetchone()
        return row[0] if row else None

    def mandatory_rule_days(self) -> list[tuple[str, Decimal, int]]:
        """Обязательные платежи по правилам с суммой: (категория, сумма, обычный день месяца).

        День — когда последний раз переводили этому получателю; не переводили — 1-е число.
        """
        with self._cursor() as cur:
            cur.execute(
                "SELECT coalesce(p.name, c.name), r.amount,"
                " coalesce((SELECT extract(day FROM max(o.operated_at))::int"
                "  FROM expense_operations o WHERE o.user_id = r.user_id"
                "  AND o.counterparty = r.pattern AND o.amount < 0), 1)"
                " FROM expense_rules r JOIN expense_categories c ON c.id = r.category_id"
                " LEFT JOIN expense_categories p ON p.id = c.parent_id"
                " JOIN expense_groups g ON g.id = coalesce(p.group_id, c.group_id)"
                " WHERE r.user_id = %s AND r.amount IS NOT NULL AND g.code = 'mandatory'",
                (self._user_id,),
            )
            return list(cur.fetchall())
