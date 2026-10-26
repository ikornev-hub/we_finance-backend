"""Категория операции: правила пользователя → словарь → MCC (требования system/expenses.md §2.4)."""

from dataclasses import dataclass
from decimal import Decimal

from we_finance.expenses.classify import OperationType
from we_finance.expenses.statement import StatementOperation

UNCATEGORIZED = "Неопределённые"
CREDIT = "Кредит"
INCOME = "Доход"
# Пока банк один, перевод себе — расход (решение 2026-10-26); нейтральным станет со вторым банком.
OWN_TRANSFER = "Переводы себе"
# Жильё вычитается из дохода вместе с кредитом (располагаемый), поэтому системная.
HOUSING = "Жильё"

# Стартовое дерево: категория → подкатегории. Каждому пользователю — копия, дальше он меняет её сам.
DEFAULT_TREE: dict[str, list[str]] = {
    "Еда": ["Продукты", "Алкоголь"],
    "Тусовки": ["Рестораны", "Кафе и доставка", "Бары"],
    "Машина": [
        "Бензин",
        "Мойка",
        "Обслуживание и страховка",
        "Парковка",
        "Платные дороги",
        "Штрафы",
    ],
    "Транспорт": ["Такси", "Общественный"],
    "Здоровье": ["Аптека", "Медуслуги"],
    "Близкие": ["Переводы", "Цветы и подарки"],
    "Связь": ["Мобильная", "Интернет и VPN"],
    HOUSING: ["Аренда", "ЖКХ"],
    "Одежда": [],
    "Налоги и штрафы": [],
    "Крупные покупки": [],
    "Маркетплейсы": [],
    "Прочее": ["Доставка"],
    OWN_TRANSFER: [],
    CREDIT: [],
    INCOME: [],
    UNCATEGORIZED: [],
}

# MCC — международный код типа магазина → «Категория/Подкатегория».
MCC: dict[str, str] = {
    "5411": "Еда/Продукты",
    "5499": "Еда/Продукты",
    "5921": "Еда/Алкоголь",
    "5812": "Тусовки/Рестораны",
    "5813": "Тусовки/Бары",
    "5814": "Тусовки/Кафе и доставка",
    "5541": "Машина/Бензин",
    "5542": "Машина/Бензин",
    "7542": "Машина/Мойка",
    "7523": "Машина/Парковка",
    "4784": "Машина/Платные дороги",
    "5511": "Машина/Обслуживание и страховка",
    "4121": "Транспорт/Такси",
    "4111": "Транспорт/Общественный",
    "5912": "Здоровье/Аптека",
    "8011": "Здоровье/Медуслуги",
    "8099": "Здоровье/Медуслуги",
    "5992": "Близкие/Цветы и подарки",
    "5651": "Одежда",
    "5691": "Одежда",
    "4214": "Прочее/Доставка",
}

# Словарь: подстрока описания → категория (то, что MCC не скажет). Как лист «Справочник».
KNOWN: dict[str, str] = {
    "MoiteSami": "Машина/Мойка",
    "Мобильная связь": "Связь/Мобильная",
    "штрафа ГИБДД": "Машина/Штрафы",
}


@dataclass(frozen=True)
class Rule:
    """Правило пользователя: «этот получатель / этот мерчант → категория»."""

    match_kind: str  # "counterparty" | "merchant"
    pattern: str
    category: str
    amount: Decimal | None = None  # для counterparty: сумма ±1 %


def _matches(rule: Rule, op: StatementOperation) -> bool:
    """Подходит ли правило к операции."""
    if rule.match_kind == "counterparty":
        if op.counterparty != rule.pattern:
            return False
        return rule.amount is None or abs(abs(op.amount) - rule.amount) <= rule.amount / 100
    return rule.pattern.lower() in f"{op.merchant or ''} {op.description}".lower()


def category_for(op: StatementOperation, kind: OperationType, rules: list[Rule]) -> str:
    """Категория «Категория/Подкатегория».

    Перевод себе: ушло — «Переводы себе» (расход), пришло — решает пользователь.
    """
    if kind == OperationType.TRANSFER_OWN:
        return OWN_TRANSFER if op.amount < 0 else UNCATEGORIZED
    if kind == OperationType.TRANSFER_CREDIT:
        return CREDIT
    if kind == OperationType.INCOME:
        return INCOME
    for rule in rules:
        if _matches(rule, op):
            return rule.category
    for pattern, category in KNOWN.items():
        if pattern.lower() in op.description.lower():
            return category
    return MCC.get(op.mcc or "", UNCATEGORIZED)
