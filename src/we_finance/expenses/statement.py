"""Разбор банковских выписок в операции одного вида."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import BinaryIO

import openpyxl

_DAY = re.compile(r"\d\d\.\d\d\.\d{4}")
_MCC = re.compile(r"MCC:\s*(\d{4})")
_PLACE = re.compile(r"место совершения операции:\s*[A-Z]{2}/[^/]+/([^,]+)")
# «на +7 (900) 000-00-05» (исходящие СБП) и «от +79000000005» (входящие) — один и тот же номер.
_PHONE = re.compile(r"(?:на|от) \+7 ?\(?(\d{3})\)? ?(\d{3})-?(\d{2})-?(\d{2})")
# Оплата по QR (#44): «…Платеж C… в <магазин> через Систему быстрых платежей» и
# Alfa Pay «…по QR коду. Получатель <магазин>».
_QR_SHOP = re.compile(r"Платеж C\S+ в (.+?) через Систему быстрых платежей")
_QR_RECIPIENT = re.compile(r"по QR коду\. Получатель (.+?)\s*$")
# Клиент Альфа-Банка по имени (#45): «Перевод клиенту ИВАН ИВАНОВИЧ И. по номеру…»,
# «Перевод от клиента ИВАН ИВАНОВИЧ И.. Перевод денежных средств».
_CLIENT = re.compile(r"Перевод (?:клиенту|от клиента) (.+? [А-ЯЁA-Z]\.)")


class StatementFormatError(ValueError):
    """Файл не похож на выписку этого банка → 422 с понятным текстом."""


@dataclass(frozen=True)
class StatementOperation:  # pylint: disable=too-many-instance-attributes
    """Операция из выписки — одинаковая для всех банков."""

    bank: str
    bank_operation_id: str
    day: date
    amount: Decimal
    description: str
    mcc: str | None = None
    merchant: str | None = None
    counterparty: str | None = None


def _money(text: str) -> Decimal:
    """'-1 234,56' (неразрывный пробел, запятая) → Decimal('-1234.56')."""
    return Decimal(text.replace("\xa0", "").replace(" ", "").replace(",", "."))


@dataclass(frozen=True)
class Statement:
    """Выписка целиком: за какой период и какие операции."""

    period_from: date | None
    period_to: date | None
    operations: list[StatementOperation]


_PERIOD = re.compile(r"За период с (\d{2}\.\d{2}\.\d{4}) по (\d{2}\.\d{2}\.\d{4})")


def _day(text: str) -> date:
    return datetime.strptime(text, "%d.%m.%Y").date()


def read_alfa(source: Path | BinaryIO) -> Statement:
    """Выписка Альфа-Банка (XLSX): период из шапки, таблица — под строкой «Дата операции»."""
    rows = list(
        openpyxl.load_workbook(source, read_only=True, data_only=True).active.iter_rows(
            values_only=True
        )
    )
    header = next((i for i, row in enumerate(rows) if row and row[0] == "Дата операции"), None)
    if header is None:
        raise StatementFormatError("Это не выписка Альфа-Банка: нет таблицы «Дата операции»")
    period = next(
        (
            found
            for row in rows[:header]
            for cell in row or ()
            if cell and (found := _PERIOD.search(str(cell)))
        ),
        None,
    )
    return Statement(
        _day(period.group(1)) if period else None,
        _day(period.group(2)) if period else None,
        _operations(rows[header + 1 :]),
    )


def parse_alfa(source: Path | BinaryIO) -> list[StatementOperation]:
    """Операции выписки Альфа-Банка (без шапки)."""
    return read_alfa(source).operations


def _counterparty(phone: re.Match | None, client: re.Match | None) -> str | None:
    """Получатель или отправитель: номер телефона, иначе имя клиента Альфа-Банка."""
    if phone:
        return "+7" + "".join(phone.groups())
    return client.group(1).strip() if client else None


def _operations(rows: list[tuple]) -> list[StatementOperation]:
    """Строки таблицы операций → операции; строки не с датой пропускаются."""
    operations = []
    for row in rows:
        if not row or not row[0] or not _DAY.fullmatch(str(row[0])):
            continue
        description = str(row[11])
        mcc = _MCC.search(description)
        merchant = _PLACE.search(description) or _QR_SHOP.search(description)
        merchant = merchant or _QR_RECIPIENT.search(description)
        phone = _PHONE.search(description)
        client = _CLIENT.search(description)
        operations.append(
            StatementOperation(
                bank="alfa",
                bank_operation_id=str(row[3]),
                day=_day(str(row[0])),
                amount=_money(str(row[12])),
                description=description,
                mcc=mcc.group(1) if mcc else None,
                merchant=merchant.group(1).strip() if merchant else None,
                counterparty=_counterparty(phone, client),
            )
        )
    return operations
