"""Расходы в Postgres: категории, загрузки, операции, правила, свои счета."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

import psycopg2
from psycopg2 import errorcodes

from we_finance.expenses.categories import (
    CREDIT,
    DEFAULT_TREE,
    HOUSING,
    INCOME,
    OWN_TRANSFER,
    UNCATEGORIZED,
    Rule,
)
from we_finance.expenses.classify import OperationType, Owner
from we_finance.expenses.errors import ExpenseError
from we_finance.expenses.income_check import Receipt
from we_finance.expenses.report import Flow, LimitedCategory
from we_finance.expenses.statement import StatementOperation

# Системные категории: на них опирается автоматика, удалять нельзя (бизнес-требования).
SYSTEM_CODES = {
    UNCATEGORIZED: "uncategorized",
    CREDIT: "credit",
    INCOME: "income",
    "Маркетплейсы": "marketplace",
    OWN_TRANSFER: "own_transfer",
    HOUSING: "housing",
}
# Код системной категории → имя, под которым её знает ядро (пользователь мог переименовать).
CODE_NAMES = {code: name for name, code in SYSTEM_CODES.items()}


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


@dataclass(frozen=True)
class StoredOperation:  # pylint: disable=too-many-instance-attributes  # поля = контракт API
    """Операция из базы, как её видит пользователь: с путём категории."""

    id: str
    operated_at: date
    amount: Decimal
    description: str
    merchant: str | None
    counterparty: str | None
    type: OperationType
    category_id: str | None
    category_path: str | None  # «Категория/Подкатегория»; None — нейтральная


@dataclass(frozen=True)
class CategoryChild:
    """Подкатегория в дереве."""

    id: str
    name: str


@dataclass(frozen=True)
class StoredCategory:
    """Категория с подкатегориями; parent_id — у подкатегории."""

    id: str
    name: str
    parent_id: str | None
    system_code: str | None
    target_share: Decimal | None
    target_amount: Decimal | None
    children: list[CategoryChild]


@dataclass(frozen=True)
class StoredAccount:
    """Свой счёт или номер из базы."""

    id: str
    bank: str
    name: str
    kind: str
    number_tail: str | None
    phone: str | None
    loan_id: str | None


@dataclass(frozen=True)
class StoredRule:
    """Правило из базы: «этот получатель / мерчант → категория»."""

    id: str
    match_kind: str
    pattern: str
    category_id: str


# Операция с путём категории; WHERE дописывает вызывающий метод.
_OPERATIONS_SQL = (
    "SELECT o.id, o.operated_at::date, o.amount, o.description, o.merchant, o.counterparty,"
    " o.type, o.category_id,"
    " CASE WHEN p.name IS NULL THEN c.name ELSE p.name || '/' || c.name END"
    " FROM expense_operations o"
    " LEFT JOIN expense_categories c ON c.id = o.category_id"
    " LEFT JOIN expense_categories p ON p.id = c.parent_id"
)


# Неразобранная операция подходит под правило (kind, pattern) — как categories._matches.
_UNCATEGORIZED_MATCH = (
    " c.system_code = 'uncategorized' AND o.user_id = %(user)s"
    " AND CASE WHEN %(kind)s = 'counterparty' THEN o.counterparty = %(pattern)s"
    " ELSE position(lower(%(pattern)s)"
    " IN lower(coalesce(o.merchant, '') || ' ' || o.description)) > 0 END"
)


def _operation(row: tuple) -> StoredOperation:
    """Строка _OPERATIONS_SQL → операция."""
    op_id, day, amount, *texts, kind, category_id, path = row
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return StoredOperation(op_id, day, amount, *texts, OperationType(kind), category_id, path)


class _Postgres:  # pylint: disable=too-few-public-methods  # база для тематических частей
    """Подключение к базе от имени одного пользователя."""

    def __init__(self, database_url: str, user_id: str) -> None:
        self._url = database_url
        self._user_id = user_id

    @contextmanager
    def _cursor(self) -> Iterator:
        """Курсор в одной транзакции: вышли без ошибки — COMMIT, с ошибкой — ROLLBACK."""
        conn = psycopg2.connect(self._url)
        try:
            with conn, conn.cursor() as cur:
                yield cur
        finally:
            conn.close()


class _Categories(_Postgres):
    """Дерево категорий пользователя."""

    def category_ids(self) -> dict[str, str]:
        """«Категория» и «Категория/Подкатегория» → id. Категорий нет — заводит стартовое дерево.

        Системные — ещё и под именем ядра («Кредит»): пользователь мог их переименовать.
        """
        with self._cursor() as cur:
            self._ensure_tree(cur)
            cur.execute(
                "SELECT c.id, c.name, p.name, c.system_code FROM expense_categories c"
                " LEFT JOIN expense_categories p ON p.id = c.parent_id"
                " WHERE c.user_id = %s",
                (self._user_id,),
            )
            ids = {}
            for category_id, name, parent, code in cur.fetchall():
                ids[f"{parent}/{name}" if parent else name] = category_id
                if code in CODE_NAMES:
                    ids[CODE_NAMES[code]] = category_id
            return ids

    def _ensure_tree(self, cur) -> None:
        """Первый вход в «Расходы» — стартовое дерево; появилась новая системная — дозавести."""
        cur.execute("SELECT count(*) FROM expense_categories WHERE user_id = %s", (self._user_id,))
        if cur.fetchone()[0] == 0:
            self._create_default_tree(cur)
        cur.execute(
            "SELECT system_code FROM expense_categories"
            " WHERE user_id = %s AND system_code IS NOT NULL",
            (self._user_id,),
        )
        have = {row[0] for row in cur.fetchall()}
        for name, code in SYSTEM_CODES.items():
            if code not in have:
                self._add_system_category(cur, name, code)

    def _add_system_category(self, cur, name: str, code: str) -> None:
        """Системная категория у старого пользователя; есть своя с таким именем — она и станет ею.

        «Переводы себе» (2026-10-26): операции, которые были нейтральными, — ушедшие сюда,
        пришедшие — в «Неопределённые».
        """
        cur.execute(
            "INSERT INTO expense_categories (id, user_id, name, system_code)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT ON CONSTRAINT expense_categories_unique_name"
            " DO UPDATE SET system_code = EXCLUDED.system_code RETURNING id",
            (uuid4().hex, self._user_id, name, code),
        )
        category_id = cur.fetchone()[0]
        if code != SYSTEM_CODES[OWN_TRANSFER]:
            return
        cur.execute(
            "UPDATE expense_operations SET category_id = %s"
            " WHERE user_id = %s AND category_id IS NULL AND amount < 0",
            (category_id, self._user_id),
        )
        cur.execute(
            "UPDATE expense_operations SET category_id = ("
            "SELECT id FROM expense_categories WHERE user_id = %(user)s"
            " AND system_code = 'uncategorized')"
            " WHERE user_id = %(user)s AND category_id IS NULL AND amount > 0",
            {"user": self._user_id},
        )

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

    def categories(self) -> list[StoredCategory]:
        """Дерево: обычные по имени, системные в конце; подкатегории по имени."""
        with self._cursor() as cur:
            self._ensure_tree(cur)
            cur.execute(
                "SELECT id, parent_id, name, system_code, target_share, target_amount"
                " FROM expense_categories"
                " WHERE user_id = %s ORDER BY system_code IS NOT NULL, name",
                (self._user_id,),
            )
            rows = cur.fetchall()
        children: dict[str, list[CategoryChild]] = {}
        for category_id, parent_id, name, *_ in rows:
            if parent_id:
                children.setdefault(parent_id, []).append(CategoryChild(category_id, name))
        return [
            StoredCategory(
                category_id, name, None, code, share, amount, children.get(category_id, [])
            )
            for category_id, parent_id, name, code, share, amount in rows
            if parent_id is None
        ]

    def category(self, category_id: str) -> StoredCategory | None:
        """Категория пользователя с подкатегориями; нет — None."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT id, name, parent_id, system_code, target_share, target_amount"
                " FROM expense_categories WHERE user_id = %s AND id = %s",
                (self._user_id, category_id),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                "SELECT id, name FROM expense_categories"
                " WHERE user_id = %s AND parent_id = %s ORDER BY name",
                (self._user_id, category_id),
            )
            return StoredCategory(*row, [CategoryChild(*child) for child in cur.fetchall()])

    def has_category(self, category_id: str) -> bool:
        """Есть ли у пользователя такая категория."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT 1 FROM expense_categories WHERE user_id = %s AND id = %s",
                (self._user_id, category_id),
            )
            return cur.fetchone() is not None

    def system_category_id(self, code: str) -> str:
        """id системной категории по коду: "uncategorized", "credit", …"""
        with self._cursor() as cur:
            self._ensure_tree(cur)
            cur.execute(
                "SELECT id FROM expense_categories WHERE user_id = %s AND system_code = %s",
                (self._user_id, code),
            )
            return cur.fetchone()[0]

    def add_category(self, name: str, parent_id: str | None, target_share: Decimal | None) -> str:
        """Новая категория или подкатегория; такое имя на этом уровне уже есть — ExpenseError."""
        category_id = uuid4().hex
        try:
            with self._cursor() as cur:
                self._ensure_tree(cur)
                cur.execute(
                    "INSERT INTO expense_categories (id, user_id, parent_id, name, target_share)"
                    " VALUES (%s, %s, %s, %s, %s)",
                    (category_id, self._user_id, parent_id, name, target_share),
                )
        except psycopg2.IntegrityError as exc:
            if exc.pgcode != errorcodes.UNIQUE_VIOLATION:
                raise
            raise ExpenseError(f"Категория «{name}» здесь уже есть") from exc
        return category_id

    def rename_category(self, category_id: str, name: str) -> None:
        """Новое имя; занято на этом уровне — ExpenseError."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    "UPDATE expense_categories SET name = %s WHERE user_id = %s AND id = %s",
                    (name, self._user_id, category_id),
                )
        except psycopg2.IntegrityError as exc:
            if exc.pgcode != errorcodes.UNIQUE_VIOLATION:
                raise
            raise ExpenseError(f"Категория «{name}» здесь уже есть") from exc

    def set_limit(
        self, category_id: str, target_share: Decimal | None, target_amount: Decimal | None
    ) -> None:
        """Граница: доля располагаемого или сумма (одно из двух); оба None — без границы."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE expense_categories SET target_share = %s, target_amount = %s"
                " WHERE user_id = %s AND id = %s",
                (target_share, target_amount, self._user_id, category_id),
            )

    def limited_tree(self) -> list[LimitedCategory]:
        """Дерево для отчёта месяца: границы и подкатегории."""
        return [
            LimitedCategory(
                c.id,
                c.name,
                c.system_code,
                c.target_share,
                c.target_amount,
                [(child.id, child.name) for child in c.children],
            )
            for c in self.categories()
        ]

    def housing_plan(self) -> Decimal:
        """Жильё по плану: суммы правил с суммой, которые ведут в «Жильё» (аренда 30 000)."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT coalesce(sum(r.amount), 0) FROM expense_rules r"
                " JOIN expense_categories c ON c.id = r.category_id"
                " LEFT JOIN expense_categories p ON p.id = c.parent_id"
                " WHERE r.user_id = %s AND r.amount IS NOT NULL"
                " AND 'housing' IN (c.system_code, p.system_code)",
                (self._user_id,),
            )
            return cur.fetchone()[0]

    def delete_category(self, category_id: str, move_to: str) -> None:
        """Удалить с подкатегориями: их операции — в move_to, их правила — удалить."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT id FROM expense_categories WHERE user_id = %s AND parent_id = %s",
                (self._user_id, category_id),
            )
            ids = [category_id, *(row[0] for row in cur.fetchall())]
            cur.execute(
                "UPDATE expense_operations SET category_id = %s"
                " WHERE user_id = %s AND category_id = ANY(%s)",
                (move_to, self._user_id, ids),
            )
            cur.execute(
                "DELETE FROM expense_rules WHERE user_id = %s AND category_id = ANY(%s)",
                (self._user_id, ids),
            )
            cur.execute(
                "DELETE FROM expense_categories WHERE user_id = %s AND parent_id = %s",
                (self._user_id, category_id),
            )
            cur.execute(
                "DELETE FROM expense_categories WHERE user_id = %s AND id = %s",
                (self._user_id, category_id),
            )


class _Accounts(_Postgres):
    """Свои счета и номера: переводы на них — себе или в кредит."""

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

    def accounts(self) -> list[StoredAccount]:
        """Свои счета и номера: сначала свои, потом кредитные; внутри — по имени."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT id, bank, name, kind, number_tail, phone, loan_id FROM expense_accounts"
                " WHERE user_id = %s ORDER BY kind DESC, name",
                (self._user_id,),
            )
            return [StoredAccount(*row) for row in cur.fetchall()]

    def account(self, account_id: str) -> StoredAccount | None:
        """Один счёт пользователя; нет — None."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT id, bank, name, kind, number_tail, phone, loan_id FROM expense_accounts"
                " WHERE user_id = %s AND id = %s",
                (self._user_id, account_id),
            )
            row = cur.fetchone()
        return StoredAccount(*row) if row else None

    def delete_account(self, account_id: str) -> bool:
        """Удалить счёт; False — такого нет."""
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM expense_accounts WHERE user_id = %s AND id = %s",
                (self._user_id, account_id),
            )
            return cur.rowcount == 1

    def has_loan(self, loan_id: str) -> bool:
        """Есть ли у пользователя такой кредит (для счёта кредита)."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT 1 FROM loans WHERE user_id = %s AND id = %s", (self._user_id, loan_id)
            )
            return cur.fetchone() is not None


class PostgresExpenseRepository(_Categories, _Accounts):
    """Расходы одного пользователя: категории, счета, загрузки, операции, правила."""

    def save_import(
        self,
        bank: str,
        file_name: str,
        items: list[ClassifiedOperation],
        period: tuple[date | None, date | None] = (None, None),
    ) -> ImportResult:
        """Сохранить загрузку; операции, которые уже были, пропускаются (UNIQUE в базе)."""
        ids = self.category_ids()
        none_id = ids[UNCATEGORIZED]
        import_id = uuid4().hex
        new = uncategorized = 0
        conn = psycopg2.connect(self._url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO expense_imports"
                        " (id, user_id, bank, file_name, period_from, period_to)"
                        " VALUES (%s, %s, %s, %s, %s, %s)",
                        (import_id, self._user_id, bank, file_name, *period),
                    )
                    for item in items:
                        op = item.operation
                        # Категорию из MCC пользователь переименовал или удалил — разберёт сам.
                        category_id = ids.get(item.category, none_id) if item.category else None
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
                                category_id,
                            ),
                        )
                        if cur.rowcount == 1:
                            new += 1
                            uncategorized += category_id == none_id
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

    def operations(
        self, start: date | None, end: date | None, category_id: str | None, uncategorized: bool
    ) -> list[StoredOperation]:
        """Операции по порядку; фильтры: период [start, end), категория с подкатегориями, разбор."""
        with self._cursor() as cur:
            cur.execute(
                _OPERATIONS_SQL + " WHERE o.user_id = %(user)s"
                " AND (%(start)s::date IS NULL OR o.operated_at >= %(start)s)"
                " AND (%(end)s::date IS NULL OR o.operated_at < %(end)s)"
                " AND (%(category)s::text IS NULL"
                " OR o.category_id = %(category)s OR c.parent_id = %(category)s)"
                " AND (NOT %(uncategorized)s OR c.system_code = 'uncategorized')"
                " ORDER BY o.operated_at, o.bank_operation_id",
                {
                    "user": self._user_id,
                    "start": start,
                    "end": end,
                    "category": category_id,
                    "uncategorized": uncategorized,
                },
            )
            return [_operation(row) for row in cur.fetchall()]

    def operation(self, operation_id: str) -> StoredOperation | None:
        """Одна операция; чужая или несуществующая — None."""
        with self._cursor() as cur:
            cur.execute(
                _OPERATIONS_SQL + " WHERE o.user_id = %s AND o.id = %s",
                (self._user_id, operation_id),
            )
            row = cur.fetchone()
        return _operation(row) if row else None

    def similar(self, operation_id: str, rule: tuple[str, str]) -> list[StoredOperation]:
        """Неразобранные операции, кроме этой, которые правило (match_kind, pattern) заберёт."""
        with self._cursor() as cur:
            return self._similar(cur, operation_id, rule)

    def _similar(self, cur, operation_id: str, rule: tuple[str, str]) -> list[StoredOperation]:
        match_kind, pattern = rule
        cur.execute(
            _OPERATIONS_SQL
            + " WHERE o.id <> %(id)s AND"
            + _UNCATEGORIZED_MATCH
            + " ORDER BY o.operated_at, o.bank_operation_id",
            {"id": operation_id, "user": self._user_id, "kind": match_kind, "pattern": pattern},
        )
        return [_operation(row) for row in cur.fetchall()]

    def set_category(
        self, operation_id: str, category_id: str, rule: tuple[str, str] | None
    ) -> tuple[StoredRule | None, list[str]]:
        """Категория операции от пользователя; rule = (match_kind, pattern) — запомнить.

        Правило без суммы на тот же шаблон одно: повторное «запомнить» меняет его категорию.
        Неразобранные операции с тем же шаблоном раскладываются сразу — их id во втором поле.
        """
        with self._cursor() as cur:
            cur.execute(
                "UPDATE expense_operations SET category_id = %s, category_source = 'user'"
                " WHERE user_id = %s AND id = %s",
                (category_id, self._user_id, operation_id),
            )
            if rule is None:
                return None, []
            match_kind, pattern = rule
            cur.execute(
                "UPDATE expense_rules SET category_id = %s"
                " WHERE user_id = %s AND match_kind = %s AND pattern = %s AND amount IS NULL"
                " RETURNING id",
                (category_id, self._user_id, match_kind, pattern),
            )
            found = cur.fetchone()
            rule_id = found[0] if found else uuid4().hex
            if not found:
                cur.execute(
                    "INSERT INTO expense_rules (id, user_id, match_kind, pattern, category_id)"
                    " VALUES (%s, %s, %s, %s, %s)",
                    (rule_id, self._user_id, match_kind, pattern, category_id),
                )
            applied = [op.id for op in self._similar(cur, operation_id, rule)]
            cur.execute(
                "UPDATE expense_operations SET category_id = %s, category_source = 'rule'"
                " WHERE user_id = %s AND id = ANY(%s)",
                (category_id, self._user_id, applied),
            )
        return StoredRule(rule_id, match_kind, pattern, category_id), applied

    def month_flows(self, start: date, end: date) -> dict[str, Flow]:
        """Категория → ушло, пришло и число операций за период [start, end)."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT category_id,"
                " coalesce(sum(-amount) FILTER (WHERE amount < 0), 0),"
                " coalesce(sum(amount) FILTER (WHERE amount > 0), 0),"
                " count(*)"
                " FROM expense_operations"
                " WHERE user_id = %s AND operated_at >= %s AND operated_at < %s"
                " AND category_id IS NOT NULL"
                " GROUP BY category_id",
                (self._user_id, start, end),
            )
            return {row[0]: Flow(*row[1:]) for row in cur.fetchall()}

    def statement_periods(self) -> list[tuple[date, date]]:
        """За какие дни есть выписки: период из шапки, иначе — от первой до последней операции."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT coalesce(i.period_from, min(o.operated_at)::date),"
                " coalesce(i.period_to, max(o.operated_at)::date)"
                " FROM expense_imports i"
                " LEFT JOIN expense_operations o ON o.import_id = i.id"
                " WHERE i.user_id = %s GROUP BY i.id",
                (self._user_id,),
            )
            return [(start, end) for start, end in cur.fetchall() if start and end]

    def income_receipts(self, start: date, end: date) -> list[Receipt]:
        """Поступления в «Доход» (с подкатегориями) за период [start, end)."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT o.operated_at::date, o.amount, o.description FROM expense_operations o"
                " JOIN expense_categories c ON c.id = o.category_id"
                " LEFT JOIN expense_categories p ON p.id = c.parent_id"
                " WHERE o.user_id = %s AND o.amount > 0"
                " AND 'income' IN (c.system_code, p.system_code)"
                " AND o.operated_at >= %s AND o.operated_at < %s"
                " ORDER BY o.operated_at",
                (self._user_id, start, end),
            )
            return [Receipt(*row) for row in cur.fetchall()]
