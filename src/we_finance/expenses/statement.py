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
_PHONE = re.compile(r"(?:на|от) \+7 \((\d{3})\) (\d{3})-(\d{2})-(\d{2})")


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


def _operations(rows: list[tuple]) -> list[StatementOperation]:
    """Строки таблицы операций → операции; строки не с датой пропускаются."""
    operations = []
    for row in rows:
        if not row or not row[0] or not _DAY.fullmatch(str(row[0])):
            continue
        description = str(row[11])
        mcc = _MCC.search(description)
        place = _PLACE.search(description)
        phone = _PHONE.search(description)
        operations.append(
            StatementOperation(
                bank="alfa",
                bank_operation_id=str(row[3]),
                day=_day(str(row[0])),
                amount=_money(str(row[12])),
                description=description,
                mcc=mcc.group(1) if mcc else None,
                merchant=place.group(1).strip() if place else None,
                counterparty="+7" + "".join(phone.groups()) if phone else None,
            )
        )
    return operations
