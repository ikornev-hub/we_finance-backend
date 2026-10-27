"""Категория операции: правила пользователя → словарь → MCC (требования system/expenses.md §2.4)."""

import re
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
# Снятие наличных — расход фактом снятия, на что потрачены, не разбираем (бизнес-требования).
CASH = "Наличные"
# Переводы на накопительный счёт цели — не трата, а «Отложено» (решение 2026-10-26).
SAVINGS = "Накопления"

# Стартовое дерево: категория → подкатегории. Каждому пользователю — копия, дальше он меняет её сам.
DEFAULT_TREE: dict[str, list[str]] = {
    # Обязательные
    "Близкие": ["Переводы", "Подарки"],
    "Связь": [],
    HOUSING: [],
    CREDIT: [],  # подкатегории — по одной на кредит, заводятся сами
    # Управляемые
    "Еда": ["Продукты", "Тусовки"],
    "Транспорт": ["Бензин", "Обслуживание", "Такси"],
    "Покупки": ["Маркетплейсы", "Одежда", "Прочее"],
    # Неуправляемые
    "Штрафы": [],
    "Здоровье": [],
    CASH: [],
    "Прочее": [],
    # Служебные и доход
    OWN_TRANSFER: [],
    SAVINGS: [],
    INCOME: [],
    UNCATEGORIZED: [],
}

# Группы трат (решение 2026-10-26): код → имя; порядок — как в отчёте.
GROUPS: dict[str, str] = {
    "mandatory": "Обязательные",
    "managed": "Управляемые",
    "unmanaged": "Неуправляемые",
    "purchases": "Покупки",
}
# Стартовая раскладка категорий по группам; None — «Служебные». Чего нет — «Управляемые».
DEFAULT_GROUP: dict[str, str | None] = {
    "Близкие": "mandatory",
    "Связь": "mandatory",
    HOUSING: "mandatory",
    CREDIT: "mandatory",
    "Еда": "managed",
    "Транспорт": "managed",
    "Покупки": "managed",
    "Штрафы": "unmanaged",
    "Здоровье": "unmanaged",
    CASH: "unmanaged",
    "Прочее": "unmanaged",
    OWN_TRANSFER: None,
    SAVINGS: None,
    UNCATEGORIZED: None,
    INCOME: None,
}

# MCC — международный код типа магазина → «Категория/Подкатегория».
MCC: dict[str, str] = {
    "5411": "Еда/Продукты",
    "5499": "Еда/Продукты",
    "5921": "Еда/Тусовки",  # алкоголь — к тусовкам (решение 2026-10-27)
    "5812": "Еда/Тусовки",
    "5813": "Еда/Тусовки",
    "5814": "Еда/Тусовки",
    "5541": "Транспорт/Бензин",
    "5542": "Транспорт/Бензин",
    "7542": "Транспорт",  # мойка
    "7523": "Транспорт",  # парковка
    "4784": "Транспорт",  # платные дороги
    "5511": "Транспорт/Обслуживание",
    "4121": "Транспорт/Такси",
    "4111": "Транспорт",  # общественный
    "5912": "Здоровье",
    "8011": "Здоровье",
    "8099": "Здоровье",
    "5992": "Близкие/Подарки",
    "5651": "Покупки/Одежда",
    "5691": "Покупки/Одежда",
    "4214": "Покупки/Прочее",  # доставка
    # решения 2026-10-27 по разбору выписок 2023–2026
    "5993": "Покупки/Прочее",  # табак, вейпы
    "5399": "Покупки/Маркетплейсы",  # Yandex Pay / Маркет
    "5200": "Покупки/Прочее",  # стройматериалы
    "5712": "Покупки/Прочее",  # мебель
    "5977": "Покупки/Прочее",  # косметика
    "8999": "Покупки/Прочее",  # СДЭК и прочие услуги
    "4722": "Транспорт",  # билеты, турагентства
    "4131": "Транспорт",  # автобусы
    "7512": "Транспорт",  # каршеринг
    "7538": "Транспорт/Обслуживание",  # автосервис
    "7298": "Еда/Тусовки",  # бани
    "7999": "Еда/Тусовки",  # сауны, развлечения
    "7832": "Еда/Тусовки",  # кино
    "7997": "Еда/Тусовки",  # фитнес-клубы
    "7991": "Еда/Тусовки",  # достопримечательности
    "5462": "Еда/Продукты",  # пекарни
    "5441": "Еда/Продукты",  # сладости, сухофрукты
    "8043": "Здоровье",  # оптика
    "6010": CASH,  # выдача наличных в отделении
    "6011": CASH,  # банкомат
}

# Словарь: подстрока описания → категория (то, что MCC не скажет). Как лист «Справочник».
KNOWN: dict[str, str] = {
    "MoiteSami": "Транспорт",
    "Мобильная связь": "Связь",
    # в PDF-выписке нет «Категория: Мобильная связь» — оператор по названию получателя
    "в пользу Билайн": "Связь",
    "в пользу Yota": "Связь",
    "в пользу МТС": "Связь",
    "в пользу Tele2": "Связь",
    "в пользу Т2": "Связь",
    "в пользу Мегафон": "Связь",
    "штрафа ГИБДД": "Штрафы",
}


@dataclass(frozen=True)
class Rule:
    """Правило пользователя: «этот получатель / этот мерчант → категория»."""

    match_kind: str  # "counterparty" | "merchant"
    pattern: str
    category: str
    amount: Decimal | None = None  # для counterparty: сумма ±1 %


# Разделители слов в названии мерчанта и описании. То же правило — в SQL (repository).
WORD_SEPARATORS = r'[\s/\\*.,;:()"«»_\-]+'
# Слова, которые ничего не говорят о магазине: номер (MCC, точки) и сама метка «MCC».
_NOISE = {"mcc"}


def pattern_words(pattern: str) -> list[str]:
    """Значимые слова шаблона: «YANDEX 5411 LAVKA» → ["yandex", "lavka"]."""
    return [
        word
        for word in re.split(WORD_SEPARATORS, pattern.lower())
        if word and not word.isdigit() and word not in _NOISE
    ]


def merchant_matches(pattern: str, text: str) -> bool:
    """Шаблон — подстрока текста или все его слова есть в тексте целыми словами (#49).

    «Yandex Lavka» ловит «YANDEX 5411 LAVKA» (слова), «UNKNOWN SHOP» — как раньше (подстрока).
    Заметки без названия («MCC 5541») слов не имеют и ничего не ловят.
    """
    text = text.lower()
    if pattern.lower() in text:
        return True
    words = pattern_words(pattern)
    return bool(words) and set(words) <= set(re.split(WORD_SEPARATORS, text))


def _matches(rule: Rule, op: StatementOperation) -> bool:
    """Подходит ли правило к операции."""
    if rule.match_kind == "counterparty":
        if op.counterparty != rule.pattern:
            return False
        return rule.amount is None or abs(abs(op.amount) - rule.amount) <= rule.amount / 100
    return merchant_matches(rule.pattern, f"{op.merchant or ''} {op.description}")


def _refine(category: str, op: StatementOperation) -> str:
    """Правило ведёт в категорию, а MCC — в её подкатегорию: берём подкатегорию.

    «Тусовки» по правилу + MCC 5814 «Тусовки/Кафе и доставка» → «Тусовки/Кафе и доставка».
    """
    by_mcc = MCC.get(op.mcc or "")
    return by_mcc if by_mcc and by_mcc.startswith(f"{category}/") else category


def category_for(op: StatementOperation, kind: OperationType, rules: list[Rule]) -> str:
    """Категория «Категория/Подкатегория».

    Перевод себе: ушло — «Переводы себе» (расход), пришло — решает пользователь.
    """
    if kind == OperationType.TRANSFER_OWN:
        return OWN_TRANSFER if op.amount < 0 else UNCATEGORIZED
    fixed = {
        OperationType.TRANSFER_CREDIT: CREDIT,
        OperationType.TRANSFER_SAVINGS: SAVINGS,
        OperationType.INCOME: INCOME,
    }
    if kind in fixed:
        return fixed[kind]
    for rule in rules:
        if _matches(rule, op):
            return _refine(rule.category, op)
    for pattern, category in KNOWN.items():
        if pattern.lower() in op.description.lower():
            return category
    return MCC.get(op.mcc or "", UNCATEGORIZED)
