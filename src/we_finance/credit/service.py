"""Сервис кредита: сценарии поверх ядра и хранилища. Про HTTP не знает (требования С1–С7)."""

from collections.abc import Sequence
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from uuid import uuid4

from we_finance.credit.models import (
    HistoryEntry,
    Loan,
    LoanStatus,
    PaymentDayChange,
    Prepayment,
    RatePeriod,
    ScheduleRow,
    StoredLoan,
)
from we_finance.credit.repository import LoanRepository
from we_finance.credit.schedule import calculate
from we_finance.credit.schemas import (
    CalculationOut,
    HistoryEntryOut,
    LoanCreateIn,
    LoanDetailOut,
    LoanIn,
    LoanStateOut,
    LoanSummaryOut,
    PrepaymentIn,
    PreviewOut,
    ScheduleItemOut,
    WarningOut,
)
from we_finance.credit.state import history_from, loan_overview, state_from


class CreditError(ValueError):
    """Ввод корректен по форме, но противоречит кредиту (ЧДП после закрытия и т. п.) → 422."""


class LoanNotFoundError(LookupError):
    """Кредита с таким id нет → 404."""


def to_loan(loan_in: LoanIn, loan_id: str = "preview", name: str = "preview") -> Loan:
    """Параметры из запроса → кредит ядра."""
    return Loan(
        id=loan_id,
        name=name,
        principal=loan_in.principal,
        rates=tuple(RatePeriod(r.start, r.annual_rate) for r in loan_in.rates),
        payment=loan_in.payment,
        months=loan_in.months,
        issue_date=loan_in.issue_date,
        first_payment_date=loan_in.first_payment_date,
        day_count=loan_in.day_count,
        weekend_shift=loan_in.weekend_shift,
        monthly_fee=loan_in.monthly_fee,
        payment_day_changes=tuple(
            PaymentDayChange(c.start, c.day) for c in loan_in.payment_day_changes
        ),
    )


def to_prepayment(prepayment_in: PrepaymentIn) -> Prepayment:
    """ЧДП из запроса → ЧДП ядра."""
    return Prepayment(prepayment_in.date, prepayment_in.amount, prepayment_in.mode)


def _unused_prepayment(
    prepayments: Sequence[Prepayment],
    applied: Sequence[HistoryEntry],
    rows: Sequence[ScheduleRow],
) -> Decimal:
    """Сколько из внесённых ЧДП не понадобилось: сверх долга, процентов и комиссии на дату."""
    used = sum((entry.amount for entry in applied), Decimal("0"))
    if applied and applied[-1].balance == 0 and rows[-1].date == applied[-1].date:
        used += rows[-1].interest + rows[-1].fee  # погашение в тот же день покрыло проценты
    return sum((p.amount for p in prepayments), Decimal("0")) - used


def _warnings(excess: Decimal) -> list[WarningOut]:
    """Предупреждения расчёта: ввод не блокируется, но пользователю стоит знать."""
    if excess <= 0:
        return []
    return [
        WarningOut(
            code="amount_exceeds_balance",
            message=f"ЧДП больше остатка долга: {excess} не учтено, кредит закрыт",
        )
    ]


def check_prepayments(loan: Loan, prepayments: Sequence[Prepayment]) -> None:
    """ЧДП позже выдачи и не позже закрытия кредита (требования 2.10)."""
    for prepayment in prepayments:
        if prepayment.date <= loan.issue_date:
            raise CreditError(
                f"ЧДП {prepayment.date} должен быть позже даты выдачи {loan.issue_date}"
            )
    rows, _ = calculate(loan, prepayments)
    _check_debt_decreases(rows)
    late = [p for p in prepayments if p.date > rows[-1].date]
    if late:
        raise CreditError(f"ЧДП {late[0].date} позже закрытия кредита {rows[-1].date}")


def _check_debt_decreases(rows: Sequence[ScheduleRow]) -> None:
    """Каждый платёж гасит долг (требования 2.10): иначе платёж меньше процентов и комиссии.

    Проверяется весь график, а не только первый период: ставка может вырасти позже.
    """
    for row in rows:
        if row.principal < 0:
            raise CreditError(
                f"Платёж {row.payment} на {row.date} меньше процентов {row.interest} "
                f"и комиссии {row.fee}: долг не уменьшается"
            )


def schedule_rows(loan: Loan) -> list[ScheduleRow]:
    """График без ЧДП с проверкой, что платёж гасит долг (калькулятор графика)."""
    check_prepayments(loan, ())
    rows, _ = calculate(loan)
    return rows


def build_calculation(loan: Loan, prepayments: Sequence[Prepayment], as_of: date) -> CalculationOut:
    """Всё о кредите на дату: стартовое и актуальное, итоги, график, история."""
    check_prepayments(loan, prepayments)
    rows, applied = calculate(loan, prepayments)
    overview = loan_overview(loan, prepayments, as_of)
    return CalculationOut(
        start=LoanStateOut.model_validate(overview.start),
        actual=LoanStateOut.model_validate(overview.actual),
        prepaid_total=overview.prepaid_total,
        interest_saved=overview.interest_saved,
        months_saved=overview.months_saved,
        schedule=[ScheduleItemOut(**asdict(row), past=row.date <= as_of) for row in rows],
        history=[HistoryEntryOut.model_validate(e) for e in history_from(rows, applied, as_of)],
        warnings=_warnings(_unused_prepayment(prepayments, applied, rows)),
    )


# ---------- сценарии над хранилищем ----------


def _get(repo: LoanRepository, loan_id: str) -> StoredLoan:
    """Кредит из хранилища или LoanNotFoundError."""
    stored = repo.get(loan_id)
    if stored is None:
        raise LoanNotFoundError(f"Кредит {loan_id} не найден")
    return stored


def loan_detail(repo: LoanRepository, loan_id: str, as_of: date) -> LoanDetailOut:
    """Кредит целиком на дату (С3–С5)."""
    stored = _get(repo, loan_id)
    calculation = build_calculation(stored.loan, stored.prepayments, as_of)
    return LoanDetailOut(
        id=stored.loan.id,
        name=stored.loan.name,
        status=stored.status,
        can_complete=can_complete(stored, as_of),
        **dict(calculation),
    )


def create_loan(repo: LoanRepository, loan_in: LoanCreateIn, as_of: date) -> LoanDetailOut:
    """Добавить кредит (С1): id выдаёт система."""
    loan = to_loan(loan_in, loan_id=uuid4().hex, name=loan_in.name)
    check_prepayments(loan, ())  # проверка до сохранения: битый кредит не должен попасть в файл
    repo.add(loan)
    return loan_detail(repo, loan.id, as_of)


def list_loans(
    repo: LoanRepository, as_of: date, status: LoanStatus = LoanStatus.ACTIVE
) -> list[LoanSummaryOut]:
    """Список кредитов в одном состоянии с остатком на дату (С2, С8)."""
    result = []
    for stored in repo.list_loans():
        if stored.status != status:
            continue
        rows, applied = calculate(stored.loan, stored.prepayments)
        state = state_from(stored.loan, rows, applied, as_of)
        result.append(
            LoanSummaryOut(
                id=stored.loan.id,
                name=stored.loan.name,
                principal=stored.loan.principal,
                balance=state.balance,
                close_date=state.close_date,
                status=stored.status,
                can_complete=stored.status == LoanStatus.ACTIVE and state.balance == 0,
            )
        )
    return result


def preview_prepayment(
    repo: LoanRepository, loan_id: str, prepayment_in: PrepaymentIn, as_of: date
) -> PreviewOut:
    """Что будет, если внести ЧДП (С6). Ничего не сохраняет."""
    stored = _get(repo, loan_id)
    new = to_prepayment(prepayment_in)
    before = build_calculation(stored.loan, stored.prepayments, as_of)
    after = build_calculation(stored.loan, (*stored.prepayments, new), max(as_of, new.date))
    return PreviewOut(
        before=before.actual,
        after=after.actual,
        interest_saved=after.interest_saved - before.interest_saved,
        months_saved=after.months_saved - before.months_saved,
        warnings=after.warnings,
    )


def add_prepayment(
    repo: LoanRepository, loan_id: str, prepayment_in: PrepaymentIn, as_of: date
) -> LoanDetailOut:
    """Внести ЧДП (С7): проверить, сохранить, вернуть кредит целиком."""
    stored = _get(repo, loan_id)
    if stored.status == LoanStatus.DELETED:
        raise CreditError("Кредит удалён: ЧДП не вносятся")

    new = to_prepayment(prepayment_in)
    check_prepayments(stored.loan, (*stored.prepayments, new))
    repo.add_prepayment(loan_id, new)
    return loan_detail(repo, loan_id, as_of)


# ---------- С8: архив ----------


def _balance(stored: StoredLoan, as_of: date) -> Decimal:
    """Остаток долга на дату."""
    rows, applied = calculate(stored.loan, stored.prepayments)
    return state_from(stored.loan, rows, applied, as_of).balance


def can_complete(stored: StoredLoan, as_of: date) -> bool:
    """Подсказать «кредит выплачен»: активный и остаток 0."""
    return stored.status == LoanStatus.ACTIVE and _balance(stored, as_of) == 0


def delete_loan(repo: LoanRepository, loan_id: str, as_of: date) -> LoanDetailOut:
    """Удалить мягко: в архив «Удалённые», в расчётах больше не участвует."""
    stored = _get(repo, loan_id)
    if stored.status == LoanStatus.DELETED:
        raise CreditError("Кредит уже удалён")
    repo.add_status(loan_id, LoanStatus.DELETED)
    return loan_detail(repo, loan_id, as_of)


def complete_loan(repo: LoanRepository, loan_id: str, as_of: date) -> LoanDetailOut:
    """В архив «Завершённые» — только активный и только при остатке 0."""
    stored = _get(repo, loan_id)
    if not can_complete(stored, as_of):
        raise CreditError("Завершить можно только активный кредит с остатком 0")
    repo.add_status(loan_id, LoanStatus.COMPLETED)
    return loan_detail(repo, loan_id, as_of)


def restore_loan(repo: LoanRepository, loan_id: str, as_of: date) -> LoanDetailOut:
    """Вернуть удалённый в то состояние, из которого удалили."""
    stored = _get(repo, loan_id)
    if stored.status != LoanStatus.DELETED:
        raise CreditError("Восстановить можно только удалённый кредит")

    previous = (
        stored.status_history[-2].status if len(stored.status_history) > 1 else LoanStatus.ACTIVE
    )
    repo.add_status(loan_id, previous)
    return loan_detail(repo, loan_id, as_of)
