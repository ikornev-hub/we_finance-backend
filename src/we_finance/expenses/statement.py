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


def parse_alfa(source: Path | BinaryIO) -> list[StatementOperation]:
    """Выписка Альфа-Банка (XLSX): таблица начинается под строкой «Дата операции»."""
    rows = list(
        openpyxl.load_workbook(source, read_only=True, data_only=True).active.iter_rows(
            values_only=True
        )
    )
    header = next((i for i, row in enumerate(rows) if row and row[0] == "Дата операции"), None)
    if header is None:
        raise StatementFormatError("Это не выписка Альфа-Банка: нет таблицы «Дата операции»")
    operations = []
    for row in rows[header + 1 :]:
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
                day=datetime.strptime(str(row[0]), "%d.%m.%Y").date(),
                amount=_money(str(row[12])),
                description=description,
                mcc=mcc.group(1) if mcc else None,
                merchant=place.group(1).strip() if place else None,
                counterparty="+7" + "".join(phone.groups()) if phone else None,
            )
        )
    return operations
