"""Расходы в Postgres: категории, загрузки, операции, правила, свои счета."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import psycopg2

from we_finance.expenses.categories import CREDIT, DEFAULT_TREE, INCOME, UNCATEGORIZED, Rule
from we_finance.expenses.classify import OperationType, Owner
from we_finance.expenses.statement import StatementOperation

# Системные категории: на них опирается автоматика, удалять нельзя (бизнес-требования).
SYSTEM_CODES = {
    UNCATEGORIZED: "uncategorized",
    CREDIT: "credit",
    INCOME: "income",
    "Маркетплейсы": "marketplace",
}


@dataclass(frozen=True)
class ClassifiedOperation:
    """Операция выписки, уже с типом и категорией — готова к сохранению."""

    operation: StatementOperation
    kind: OperationType
    category: str | None  # «Категория/Подкатегория»; None — нейтральная


@dataclass(frozen=True)
class ImportResult:
    """Итог загрузки: что пришло, что новое, что уже было."""

    import_id: str
    total: int
    new: int
    duplicates: int
    uncategorized: int


@dataclass(frozen=True)
class NewAccount:
    """Свой счёт или номер: переводы на него — себе (own) или в кредит (credit)."""

    bank: str
    name: str
    kind: str  # "own" | "credit"
    number_tail: str | None = None
    phone: str | None = None
    loan_id: str | None = None


class PostgresExpenseRepository:
    """Расходы одного пользователя."""

    def __init__(self, database_url: str, user_id: str) -> None:
        self._url = database_url
        self._user_id = user_id

    def category_ids(self) -> dict[str, str]:
        """«Категория» и «Категория/Подкатегория» → id. Категорий нет — заводит стартовое дерево."""
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT count(*) FROM expense_categories WHERE user_id = %s",
                        (self._user_id,),
                    )
                    if cur.fetchone()[0] == 0:
                        self._create_default_tree(cur)
                    cur.execute(
                        "SELECT c.id, c.name, p.name FROM expense_categories c"
                        " LEFT JOIN expense_categories p ON p.id = c.parent_id"
                        " WHERE c.user_id = %s",
                        (self._user_id,),
                    )
                    return {
                        (f"{parent}/{name}" if parent else name): category_id
                        for category_id, name, parent in cur.fetchall()
                    }
        finally:
            conn.close()

    def _create_default_tree(self, cur) -> None:
        """Стартовое дерево: сначала категория, потом её подкатегории со ссылкой на неё."""
        for name, children in DEFAULT_TREE.items():
            parent_id = uuid4().hex
            cur.execute(
                "INSERT INTO expense_categories (id, user_id, name, kind, system_code)"
                " VALUES (%s, %s, %s, %s, %s)",
                (
                    parent_id,
                    self._user_id,
                    name,
                    "income" if name == INCOME else "expense",
                    SYSTEM_CODES.get(name),
                ),
            )
            for child in children:
                cur.execute(
                    "INSERT INTO expense_categories (id, user_id, parent_id, name)"
                    " VALUES (%s, %s, %s, %s)",
                    (uuid4().hex, self._user_id, parent_id, child),
                )

    def save_import(
        self, bank: str, file_name: str, items: list[ClassifiedOperation]
    ) -> ImportResult:
        """Сохранить загрузку; операции, которые уже были, пропускаются (UNIQUE в базе)."""
        ids = self.category_ids()
        import_id = uuid4().hex
        new = uncategorized = 0
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO expense_imports (id, user_id, bank, file_name)"
                        " VALUES (%s, %s, %s, %s)",
                        (import_id, self._user_id, bank, file_name),
                    )
                    for item in items:
                        op = item.operation
                        cur.execute(
                            "INSERT INTO expense_operations (id, user_id, import_id, bank,"
                            " bank_operation_id, operated_at, amount, description, merchant, mcc,"
                            " counterparty, type, category_id)"
                            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                            " ON CONFLICT (user_id, bank, bank_operation_id) DO NOTHING",
                            (
                                uuid4().hex,
                                self._user_id,
                                import_id,
                                op.bank,
                                op.bank_operation_id,
                                datetime.combine(op.day, datetime.min.time()),
                                op.amount,
                                op.description,
                                op.merchant,
                                op.mcc,
                                op.counterparty,
                                item.kind,
                                ids[item.category] if item.category else None,
                            ),
                        )
                        if cur.rowcount == 1:
                            new += 1
                            uncategorized += item.category == UNCATEGORIZED
        finally:
            conn.close()
        return ImportResult(import_id, len(items), new, len(items) - new, uncategorized)

    def add_rule(
        self, match_kind: str, pattern: str, category: str, amount: Decimal | None = None
    ) -> None:
        """Правило «этот получатель / мерчант → категория»."""
        category_id = self.category_ids()[category]
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO expense_rules"
                        " (id, user_id, match_kind, pattern, amount, category_id)"
                        " VALUES (%s, %s, %s, %s, %s, %s)",
                        (uuid4().hex, self._user_id, match_kind, pattern, amount, category_id),
                    )
        finally:
            conn.close()

    def rules(self) -> list[Rule]:
        """Правила по приоритету: сначала получатель, потом мерчант, внутри — по очереди."""
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT r.match_kind, r.pattern, r.amount, c.name, p.name"
                        " FROM expense_rules r"
                        " JOIN expense_categories c ON c.id = r.category_id"
                        " LEFT JOIN expense_categories p ON p.id = c.parent_id"
                        " WHERE r.user_id = %s"
                        " ORDER BY r.match_kind = 'counterparty' DESC, r.created_at",
                        (self._user_id,),
                    )
                    return [
                        Rule(kind, pattern, f"{parent}/{name}" if parent else name, amount)
                        for kind, pattern, amount, name, parent in cur.fetchall()
                    ]
        finally:
            conn.close()

    def add_account(self, account: NewAccount) -> str:
        """Свой счёт или номер телефона; kind = "credit" — счёт кредита (нужен loan_id)."""
        account_id = uuid4().hex
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO expense_accounts"
                        " (id, user_id, bank, number_tail, phone, kind, loan_id, name)"
                        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            account_id,
                            self._user_id,
                            account.bank,
                            account.number_tail,
                            account.phone,
                            account.kind,
                            account.loan_id,
                            account.name,
                        ),
                    )
        finally:
            conn.close()
        return account_id

    def owner(self) -> Owner:
        """Что система знает о владельце: свои номера и банки, где лежат кредиты."""
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT kind, phone, name FROM expense_accounts WHERE user_id = %s",
                        (self._user_id,),
                    )
                    rows = cur.fetchall()
        finally:
            conn.close()
        return Owner(
            phones=frozenset(phone for kind, phone, _ in rows if kind == "own" and phone),
            credit_banks=frozenset(name for kind, _, name in rows if kind == "credit"),
        )
