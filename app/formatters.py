# app/formatters.py
from __future__ import annotations
from decimal import Decimal
from typing import Any, Dict, List, Tuple
from collections import defaultdict

# ---- Для отчёта по выручке ----
from app.models.transactions import TransactionItem, RevenueChannel


# ================================
#     СТАТУСЫ МОЕК (TMS)
# ================================

# Что считаем проблемой
PROBLEM_STATUSES = {"error", "alarm", "warning", "offline"}

# Для выбора «наихудшего» статуса
SEVERITY_RANK = {
    "ok": 0,
    "online": 0,
    "warning": 1,
    "offline": 1,
    "alarm": 2,
    "error": 2,
}


def _norm_status(s: Any) -> str:
    if not s:
        return "ok"
    return str(s).strip().lower()


def _worst(a: str, b: str) -> str:
    return a if SEVERITY_RANK.get(a, 0) >= SEVERITY_RANK.get(b, 0) else b


def _is_ignorable_warning(status: str | None, text: str | None) -> bool:
    """
    Игнорируем предупреждения вида: status == 'warning' и text == 'connection failed'
    (без учёта регистра/пробелов).
    """
    st = _norm_status(status)
    tx = (text or "").strip().lower()
    return st == "warning" and tx == "connection failed"


def _collect_problem_modules(mods: List[Dict[str, Any]] | None, out: List[Tuple[str, str, str | None]]) -> None:
    """
    Рекурсивно собираем проблемные модули: (display_name, status, text)
    """
    if not mods:
        return
    for m in mods:
        st = _norm_status(m.get("status"))
        if st != "ok":
            name = m.get("full_name") or m.get("name") or m.get("id") or "module"
            text = m.get("text")
            out.append((name, st, text))
        # рекурсивно вглубь
        _collect_problem_modules(m.get("modules"), out)


def is_bad_wash(wash: Dict[str, Any]) -> bool:
    """
    Проблемной считаем мойку, если:
    - после фильтрации остались проблемные модули (не ok, при этом НЕ warning 'connection failed'), или
    - есть error на верхнем уровне (status.type == error или online_type == error).
    Предупреждения warning 'connection failed' игнорируем.
    """
    status = (wash.get("status") or {})

    # Соберём все модульные проблемы
    problems: List[Tuple[str, str, str | None]] = []
    _collect_problem_modules(wash.get("modules"), problems)
    _collect_problem_modules(status.get("modules"), problems)

    # Отфильтруем игнорируемые warning
    problems = [
        (name, st, text)
        for (name, st, text) in problems
        if not _is_ignorable_warning(st, text)
    ]

    if problems:
        return True

    # Если модулей-проблем нет, но верхний уровень — явный error
    top = _norm_status(status.get("type"))
    online = _norm_status(status.get("online_type"))
    if top == "error" or online == "error":
        return True

    # Остальное считаем «не проблемой» для отправки (в т.ч. warning без модульных деталей)
    return False


def _worst_status_for_wash(wash: Dict[str, Any]) -> str:
    """
    Возвращает «наихудший» статус мойки на основе status.type, status.online_type и модулей.
    """
    worst = _norm_status((wash.get("status") or {}).get("type"))
    online = _norm_status((wash.get("status") or {}).get("online_type"))
    worst = _worst(worst, online)

    tmp: List[Tuple[str, str, str | None]] = []
    _collect_problem_modules(wash.get("modules"), tmp)
    _collect_problem_modules((wash.get("status") or {}).get("modules"), tmp)
    for _name, st, _text in tmp:
        worst = _worst(worst, _norm_status(st))

    return worst or "ok"


def _status_emoji(status: str) -> str:
    s = _norm_status(status)
    if s in ("error", "alarm"):
        return "🚨"
    if s in ("warning", "offline"):
        return "⚠️"
    return "✅"


def format_washes(washes: List[Dict[str, Any]], only_bad: bool = False) -> str:
    """
    Сводка статусов по списку моек.
    Если only_bad=True — выводим только проблемные.
    Для каждой проблемной мойки добавляем строки по модульным проблемам
    (игнорируя warning 'connection failed').
    """
    lines: List[str] = []
    for w in washes:
        if only_bad and not is_bad_wash(w):
            continue

        name = w.get("location_name") or w.get("location") or w.get("address") or f"ID {w.get('id')}"
        unit_id = w.get("id") or w.get("unit_id") or "-"
        worst = _worst_status_for_wash(w)
        emoji = _status_emoji(worst)

        # верхняя строка по мойке
        lines.append(f"{emoji} <b>{name}</b> — <code>{worst}</code> (id {unit_id})")

        # детализируем проблемные модули
        problems: List[Tuple[str, str, str | None]] = []
        _collect_problem_modules(w.get("modules"), problems)
        _collect_problem_modules((w.get("status") or {}).get("modules"), problems)

        # уберём дубли (одинаковые name+status+text)
        seen = set()
        unique = []
        for p in problems:
            key = (p[0], p[1], p[2] or "")
            if key not in seen:
                seen.add(key)
                unique.append(p)

        # выводим, пропуская игнорируемые warning
        for mod_name, st, text in unique:
            st_norm = _norm_status(st)
            if _is_ignorable_warning(st_norm, text):
                continue
            if text:
                lines.append(f"• <b>{mod_name}</b>: <code>{st_norm}</code> — {text}")
            else:
                lines.append(f"• <b>{mod_name}</b>: <code>{st_norm}</code>")

    if only_bad:
        if not lines:
            return "✅ Аварийных моек не обнаружено."
        header = "🚨 Сводка статусов (только проблемные)"
    else:
        header = "🧼 Сводка статусов"

    return f"{header}\n\n" + "\n".join(lines)


# ================================
#     ВЫРУЧКА (агрегация)
# ================================

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


def aggregate_revenue(transactions: List[TransactionItem]) -> RevenueReport:
    """
    Пройтись по транзакциям и собрать суммы по каналам.
    Учитываются только корректные (approved, не cancelled) — логика в моделях.
    """
    rep = RevenueReport()
    for t in transactions:
        amount, channel = t.revenue_amount_and_channel()
        if not channel or amount <= 0:
            continue
        if channel == RevenueChannel.CASH:
            rep.cash += amount
        elif channel == RevenueChannel.CARD:
            rep.card += amount
        elif channel == RevenueChannel.YANDEX_WASH:
            rep.yandex_wash += amount
    return rep


def _fmt_amount(value: Decimal) -> str:
    # Разделитель тысяч пробелом, 2 знака
    return f"{value:,.2f}".replace(",", " ")


def format_revenue_report_simple(report: RevenueReport, from_d: str, to_d: str) -> str:
    if from_d == to_d:
        header = f"📊 Выручка за {from_d}"
    else:
        header = f"📊 Выручка за период {from_d} — {to_d}"

    lines = [
        header,
        f"— Наличные:    {_fmt_amount(report.cash)} RUB",
        f"— Безнал:      {_fmt_amount(report.card)} RUB",
        f"— Yandex.Wash: {_fmt_amount(report.yandex_wash)} RUB",
        f"— Итого:       {_fmt_amount(report.total)} RUB",
    ]
    return "\n".join(lines)