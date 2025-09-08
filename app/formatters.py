# app/formatters.py
from __future__ import annotations
from decimal import Decimal
from typing import List

from app.models.transactions import TransactionItem, RevenueChannel


# ---------- Форматирование статусов ----------
def is_bad_wash(wash: dict) -> bool:
    """
    Простейший фильтр "плохих" моек:
    считаем проблемой, если статус != 'OK' (или если есть поле state/error).
    Здесь можно адаптировать под твою модель wash.
    """
    state = str(wash.get("state", "")).lower()
    error = str(wash.get("error", "")).lower()
    if state and state != "ok":
        return True
    if error and error not in {"", "ok", "none"}:
        return True
    return False


def format_washes(data: List[dict], only_bad: bool = False) -> str:
    """
    Краткая сводка по списку моек.
    """
    lines: list[str] = []
    bad_count = 0
    for w in data:
        if only_bad and not is_bad_wash(w):
            continue
        unit_id = w.get("id") or w.get("unit_id") or "?"
        state = w.get("state") or "?"
        lines.append(f"— ID {unit_id}: {state}")
        if is_bad_wash(w):
            bad_count += 1

    if not lines:
        return "✅ Все мойки в порядке."

    header = "⚠️ Сводка статусов (только аварийные)" if only_bad else "ℹ️ Сводка статусов"
    return "\n".join([header] + lines)


# ---------- Форматирование выручки ----------
class RevenueReport:
    def __init__(self, cash: Decimal = Decimal("0"),
                 card: Decimal = Decimal("0"),
                 yandex_wash: Decimal = Decimal("0")):
        self.cash = cash
        self.card = card
        self.yandex_wash = yandex_wash

    @property
    def total(self) -> Decimal:
        return self.cash + self.card + self.yandex_wash


def _fmt_amount(value: Decimal) -> str:
    # Разделитель тысяч пробелом, 2 знака после запятой
    return f"{value:,.2f}".replace(",", " ")


def format_revenue_report_simple(report: RevenueReport, from_d: str, to_d: str) -> str:
    lines: list[str] = []
    if from_d == to_d:
        lines.append(f"📊 Выручка за {from_d}")
    else:
        lines.append(f"📊 Выручка за период {from_d} — {to_d}")

    lines.append(f"— Наличные:    {_fmt_amount(report.cash)} RUB")
    lines.append(f"— Безнал:      {_fmt_amount(report.card)} RUB")
    lines.append(f"— Yandex.Wash: {_fmt_amount(report.yandex_wash)} RUB")
    lines.append(f"— Итого:       {_fmt_amount(report.total)} RUB")

    return "\n".join(lines)


# ---------- Утилита для агрегации ----------
def aggregate_revenue(transactions: List[TransactionItem]) -> RevenueReport:
    """
    Пройтись по транзакциям и собрать суммы по каналам.
    """
    report = RevenueReport()
    for t in transactions:
        amount, channel = t.revenue_amount_and_channel()
        if not channel:
            continue
        if channel == RevenueChannel.CASH:
            report.cash += amount
        elif channel == RevenueChannel.CARD:
            report.card += amount
        elif channel == RevenueChannel.YANDEX_WASH:
            report.yandex_wash += amount
    return report