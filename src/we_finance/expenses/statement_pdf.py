"""Выписка Альфа-Банка в PDF («Выписка по счету»): те же операции, что из XLSX.

Текст страниц: «ДД.ММ.ГГГГ <код> <описание…> <сумма> RUR», описание — на нескольких строках,
между страницами — подпись, «Страница N из M» и повтор шапки таблицы. Описание карточной
операции приводится к виду XLSX («…, место совершения операции: RU/<город>/<магазин>, MCC: NNNN»)
и дата — к дате совершения: так правила категорий и склейка с XLSX работают одинаково.

Оракул в самом файле: сумма поступлений и расходов обязана совпасть с шапкой выписки.
"""

import re
from datetime import date
from decimal import Decimal
from typing import BinaryIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from we_finance.expenses.statement import (
    Statement,
    StatementFormatError,
    StatementOperation,
    bank_id,
    make_operation,
    read_alfa,
    unique_ids,
)

_START = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4}) (\S+) ?(.*)$")
_AMOUNT = re.compile(r"(?<![\d.])(-?\d{1,3}(?: \d{3})*,\d{2}) RUR$")
_NOISE = re.compile(
    r"^(А\.А\. |Уполномоченное лицо|\(подпись сотрудника|Страница \d+ из \d+"
    r"|Дата проводки Код операции|в валюте счета)"
)
_PERIOD = re.compile(r"За период с (\d{2})\.(\d{2})\.(\d{4}) по (\d{2})\.(\d{2})\.(\d{4})")
_CARD = re.compile(
    r"^Операция по карте: (?P<card>\S+?), на сумму: .*?, дата совершения операции: "
    r"(?P<d>\d{2})\.(?P<m>\d{2})\.(?P<y>\d{2}), место совершения операции: (?P<place>.*?)"
    r"(?: MCC(?P<mcc>\d{4}))?$"
)


def _money(text: str) -> Decimal:
    return Decimal(text.replace(" ", "").replace(",", "."))


def _header_total(text: str, label: str) -> Decimal | None:
    found = re.search(label + r" (-?\d{1,3}(?: \d{3})*,\d{2}) RUR", text)
    return _money(found.group(1)) if found else None


def _join(head: str, line: str) -> str:
    """Склеить перенос: «156-52-» + «77» — без пробела, иначе через пробел."""
    if not head:
        return line
    return head + line if head.endswith("-") and line[:1].isdigit() else f"{head} {line}"


def _records(body: str) -> list[dict]:
    """Текст таблицы → записи {дата, код, описание, сумма}."""
    records: list[dict] = []
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("HOLD "):  # неподтверждённые блокировки — не операции
            break
        if not line or _NOISE.match(line):
            continue
        start = _START.match(line)
        if start and (not records or records[-1]["amount"] is not None):
            day, month, year, code, rest = start.groups()
            records.append(
                {
                    "day": date(int(year), int(month), int(day)),
                    "code": code,
                    "text": rest,
                    "amount": None,
                }
            )
        elif records and records[-1]["amount"] is None:
            records[-1]["text"] = _join(records[-1]["text"], line)
        else:
            raise StatementFormatError(f"Строка «{line[:60]}» не относится ни к одной операции")
        last = records[-1]
        amount = _AMOUNT.search(last["text"])
        if amount and last["amount"] is None:
            last["amount"] = _money(amount.group(1))
            last["text"] = last["text"][: amount.start()].strip()
    return records


def _operation(record: dict) -> StatementOperation:
    """Запись → операция; карточная — в виде XLSX и с датой совершения."""
    text, day = record["text"], record["day"]
    card = _CARD.match(text)
    if card:
        parts = card["place"].split("\\")
        place = "/".join(parts[1:]) if len(parts) > 3 else card["place"]  # без номера терминала
        day = date(2000 + int(card["y"]), int(card["m"]), int(card["d"]))
        text = (
            f"Операция по карте: {card['card'].replace('+', '*')},"
            f" дата создания транзакции: {day:%d-%m-%Y}, место совершения операции: {place}"
            + (f", MCC: {card['mcc']}" if card["mcc"] else "")
        )
    code = bank_id(record["code"], record["day"], record["amount"])
    return make_operation(code, day, record["amount"], text)


def read_alfa_pdf(source: BinaryIO) -> Statement:
    """Выписка Альфа-Банка в PDF → период и операции; сумма сверяется с шапкой."""
    try:
        text = "\n".join(page.extract_text() or "" for page in PdfReader(source).pages)
    except (PdfReadError, ValueError, OSError) as exc:
        raise StatementFormatError("Это не выписка: PDF не открывается") from exc
    if "Выписка по счету" not in text or "Операции по счету" not in text:
        raise StatementFormatError("Это не выписка Альфа-Банка: нет «Выписка по счету»")
    if "Счёт кредитной карты" in text:
        raise StatementFormatError(
            "Это выписка кредитной карты — пока загружаем только дебетовые счета"
        )
    records = _records(text.split("Операции по счету", 1)[1])
    broken = next((r["code"] for r in records if r["amount"] is None), None)
    if broken:
        raise StatementFormatError(f"Операция {broken}: не нашлась сумма")
    incoming = sum((r["amount"] for r in records if r["amount"] > 0), Decimal("0"))
    outgoing = -sum((r["amount"] for r in records if r["amount"] < 0), Decimal("0"))
    for label, total in (("Поступления", incoming), ("Расходы", outgoing)):
        expected = _header_total(text, label)
        if expected is not None and expected != total:
            raise StatementFormatError(
                f"{label}: по операциям {total}, в шапке выписки {expected}"
                " — файл разобран не полностью"
            )
    period = _PERIOD.search(text)
    return Statement(
        date(int(period[3]), int(period[2]), int(period[1])) if period else None,
        date(int(period[6]), int(period[5]), int(period[4])) if period else None,
        unique_ids([_operation(record) for record in records]),
        _header_total(text, "Исходящий остаток"),
    )


def read_alfa_any(source: BinaryIO) -> Statement:
    """Выписка Альфа-Банка: PDF или XLSX — по первым байтам файла."""
    head = source.read(5)
    source.seek(0)
    return read_alfa_pdf(source) if head.startswith(b"%PDF") else read_alfa(source)
