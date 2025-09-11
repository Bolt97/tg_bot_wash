from __future__ import annotations
import logging
from typing import Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from app.config import Config
from app.logging_setup import setup_logging
from app.formatters import (
    format_washes,
    is_bad_wash,
    aggregate_revenue,
    format_revenue_report_simple,
)
from app.services.tms_client import TMSClient
from app.models.transactions import TransactionsResponse

logger = logging.getLogger(__name__)

_last_poll_ok_at: Optional[datetime] = None  # время последнего успешного опроса


# ---------------- Вспомогательное ----------------
def _seconds_until_next(hour: int, minute: int, tz_name: str) -> int:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        from datetime import timedelta as _td
        next_run += _td(days=1)
    return int((next_run - now).total_seconds())


def _parse_revenue_args(args: list[str], tz_name: str) -> tuple[str, str]:
    """
    /revenue                -> сегодня (по TZ)
    /revenue ДД.ММ.ГГГГ     -> конкретная дата (from=to)
    """
    tz = ZoneInfo(tz_name)

    if not args:
        d = datetime.now(tz).date()
        return d.isoformat(), d.isoformat()

    if len(args) == 1:
        # принимаем только формат ДД.ММ.ГГГГ
        try:
            d = datetime.strptime(args[0], "%d.%m.%Y").date()
        except ValueError:
            raise ValueError("Неверная дата. Используйте формат ДД.ММ.ГГГГ, например: /revenue 09.08.2025")
        return d.isoformat(), d.isoformat()

    # временно отключаем период
    raise ValueError("Использование: /revenue или /revenue ДД.ММ.ГГГГ")


# ---------------- Статусы ----------------
async def _poll_and_send(context: ContextTypes.DEFAULT_TYPE):
    """Опрос статусов. Сообщение в чат — только если есть проблемные мойки."""
    global _last_poll_ok_at
    cfg: Config = context.application.bot_data["cfg"]

    logger.info("Polling statuses...")

    if not cfg.wash_ids:
        await context.bot.send_message(chat_id=cfg.group_chat_id, text="⚠️ Не задан список WASH_IDS.")
        return
    if not cfg.tms_cookie:
        await context.bot.send_message(chat_id=cfg.group_chat_id, text="⚠️ Не задан TMS_COOKIE.")
        return

    try:
        async with TMSClient(cfg.tms_base_url, cfg.tms_cookie) as tms:
            data, _raw, _status_code, _resp_h, _req_h = await tms.fetch_units(cfg.tms_project_id, cfg.wash_ids)

        bad_present = any(is_bad_wash(w) for w in data)
        if bad_present:
            # формируем краткую сводку ТОЛЬКО по аварийным
            text = format_washes(data, only_bad=True)
            await context.bot.send_message(
                chat_id=cfg.group_chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        else:
            logger.info("All good; no bad statuses. (no message sent)")

        _last_poll_ok_at = datetime.now(ZoneInfo(cfg.timezone))

    except Exception as e:
        logger.exception("Polling failed: %s", e)
        await context.bot.send_message(chat_id=cfg.group_chat_id, text=f"⚠️ Ошибка запроса статусов: {e}")


# ---------------- Ежедневный отчёт выручки (за вчера) ----------------
async def _send_daily_revenue_report(context: ContextTypes.DEFAULT_TYPE):
    """
    Каждый день в 00:01 (локальная TZ) отправляет выручку за вчера.
    Уходит ТОЛЬКО в REVENUE_CHAT_ID. Если не задан — пропускаем.
    """
    cfg: Config = context.application.bot_data["cfg"]
    if not cfg.revenue_chat_id:
        logger.warning("REVENUE_CHAT_ID не задан — ежедневный отчёт пропущен.")
        return

    chat_id = cfg.revenue_chat_id
    tz = ZoneInfo(cfg.timezone)

    # вчера по локальной TZ
    today_local = datetime.now(tz).date()
    yesterday = today_local - timedelta(days=1)
    date_from = yesterday.isoformat()
    date_to = yesterday.isoformat()

    try:
        async with TMSClient(cfg.tms_base_url, cfg.tms_cookie) as tms:
            data, _raw, _status, _resp_h, _req_h = await tms.fetch_transactions(
                org_id=cfg.org_id, date_from=date_from, date_to=date_to, max_count=1500
            )
        resp = TransactionsResponse.model_validate(data)
        report = aggregate_revenue(resp.items)
        text = format_revenue_report_simple(report, date_from, date_to)
        await context.bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        logger.exception("Daily revenue task failed: %s", e)
        # уведомим основной чат о проблеме, если он есть
        try:
            if cfg.group_chat_id:
                await context.bot.send_message(
                    chat_id=cfg.group_chat_id,
                    text=f"⚠️ Ошибка ежедневного отчёта выручки: {e}"
                )
        except Exception:
            pass


# ---------------- Команды ----------------
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручная сводка: покажем только аварийные, а если их нет — сообщим об этом."""
    cfg: Config = context.application.bot_data["cfg"]
    try:
        async with TMSClient(cfg.tms_base_url, cfg.tms_cookie) as tms:
            data, _raw, _status_code, _resp_h, _req_h = await tms.fetch_units(cfg.tms_project_id, cfg.wash_ids)
        bad_present = any(is_bad_wash(w) for w in data)
        text = format_washes(data, only_bad=True) if bad_present else "✅ Аварийных моек не обнаружено."
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка запроса статусов: {e}")


async def cmd_whereami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    await update.message.reply_text(f"chat_id: {chat.id}\nchat_type: {chat.type}\nuser_id: {user.id if user else 'n/a'}")


async def cmd_status_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Состояние бота и задач"""
    cfg: Config = context.application.bot_data["cfg"]
    tz = ZoneInfo(cfg.timezone)
    started_at: datetime = context.application.bot_data.get("started_at")
    uptime = None
    if started_at:
        uptime = datetime.now(tz) - started_at

    jobs = context.job_queue.jobs() if context.job_queue else []
    lines = []
    lines.append("🤖 Бот работает")
    if uptime:
        total_sec = int(uptime.total_seconds())
        h = total_sec // 3600
        m = (total_sec % 3600) // 60
        s = total_sec % 60
        lines.append(f"⏱ Uptime: {h:02d}:{m:02d}:{s:02d}")
    if _last_poll_ok_at:
        lines.append(f"🕒 Последний успешный опрос: {_last_poll_ok_at.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    else:
        lines.append("🕒 Последний успешный опрос: пока нет данных")

    if jobs:
        lines.append("🧰 Активные задачи:")
        for j in jobs:
            next_t = getattr(j, "next_t", None)
            if next_t:
                try:
                    next_local = next_t.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S %Z')
                except Exception:
                    next_local = str(next_t)
                lines.append(f"• {j.name}: след. запуск {next_local}")
            else:
                lines.append(f"• {j.name}: планирование неизвестно")
    else:
        lines.append("🧰 Активные задачи: нет")

    lines.append("")
    lines.append(f"🌐 TIMEZONE={cfg.timezone}")
    lines.append(f"📅 DAILY_REVENUE={'on' if cfg.enable_daily_revenue else 'off'} (00:01) → chat {cfg.revenue_chat_id or '-'}")
    await update.message.reply_text("\n".join(lines))


async def cmd_revenue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /revenue                -> выручка за сегодня
    /revenue ДД.ММ.ГГГГ     -> выручка за конкретную дату
    Команда работает ТОЛЬКО в REVENUE_CHAT_ID.
    """
    cfg: Config = context.application.bot_data["cfg"]

    # Разрешаем команду только в revenue-чате. В остальных — тихо игнорируем.
    if cfg.revenue_chat_id and update.effective_chat.id != cfg.revenue_chat_id:
        return

    try:
        date_from, date_to = _parse_revenue_args(context.args or [], cfg.timezone)
    except Exception as e:
        # Отвечаем только если это разрешённый чат
        if update.effective_chat.id == cfg.revenue_chat_id:
            await update.message.reply_text(f"❗ {e}")
        return

    try:
        async with TMSClient(cfg.tms_base_url, cfg.tms_cookie) as tms:
            data, _raw, _status, _resp_h, _req_h = await tms.fetch_transactions(
                org_id=cfg.org_id, date_from=date_from, date_to=date_to, max_count=1500
            )
        resp = TransactionsResponse.model_validate(data)

        report = aggregate_revenue(resp.items)
        text = format_revenue_report_simple(report, date_from, date_to)

        await update.message.reply_text(text)
    except Exception as e:
        logger.exception("Revenue fetch failed: %s", e)
        await update.message.reply_text(f"⚠️ Ошибка получения выручки: {e}")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = getattr(context, "error", None)
    logger.error("Unhandled error: %s", err)


# ---------------- Entry point ----------------
def main():
    cfg = Config.load()
    if not cfg.bot_token or not cfg.group_chat_id:
        raise RuntimeError("BOT_TOKEN/GROUP_CHAT_ID не заданы в .env")

    setup_logging(cfg.log_to_file, cfg.log_file_path)
    logger.info("Starting bot...")

    app = Application.builder().token(cfg.bot_token).build()
    app.bot_data["cfg"] = cfg
    app.bot_data["started_at"] = datetime.now(ZoneInfo(cfg.timezone))

    # команды
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("whereami", cmd_whereami))
    app.add_handler(CommandHandler("status_bot", cmd_status_bot))
    app.add_handler(CommandHandler("revenue", cmd_revenue))
    app.add_error_handler(on_error)

    if app.job_queue is None:
        raise RuntimeError("Установи extra: pip install 'python-telegram-bot[job-queue]'")

    # 1) Опрос статусов: каждые 5 минут, первый запуск сразу (first=0)
    app.job_queue.run_repeating(
        _poll_and_send,
        interval=timedelta(minutes=5),
        first=0,
        name="poll_statuses",
    )

    # 2) Ежедневная «выручка за вчера» — ближайшее 00:01 в нужной TZ, далее каждые 24 часа
    if cfg.enable_daily_revenue:
        delay = _seconds_until_next(0, 1, cfg.timezone)  # 00:01
        app.job_queue.run_repeating(
            _send_daily_revenue_report,
            interval=24 * 60 * 60,
            first=delay,
            name="daily_revenue_report",
        )
        logger.info("Daily revenue scheduled at 00:01 %s (first in %s sec)", cfg.timezone, delay)

    app.run_polling()


if __name__ == "__main__":
    main()