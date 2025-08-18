from __future__ import annotations
import json
import logging
from io import BytesIO
from typing import Optional
from datetime import time as dtime, datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import BadRequest, Forbidden

from app.config import Config
from app.logging_setup import setup_logging
from app.formatters import format_washes, is_bad_wash
from app.services.tms_client import TMSClient, redact_headers

logger = logging.getLogger(__name__)
_last_hash: Optional[str] = None

def _hash_text(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

async def _send_debug(bot: Bot, chat_id: int, title: str, body: str):
    if not chat_id:
        return
    MAX = 3800
    try:
        if len(body) <= MAX:
            await bot.send_message(
                chat_id=chat_id,
                text=f"🧪 {title}\n<pre>{body}</pre>",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        else:
            bio = BytesIO(body.encode("utf-8"))
            bio.name = f"{title.replace(' ', '_')}.txt"
            await bot.send_document(chat_id=chat_id, document=bio, caption=f"🧪 {title}")
    except (BadRequest, Forbidden) as e:
        logger.warning("debug send failed to %s: %s", chat_id, e)
    except Exception as e:
        logger.exception("unexpected debug send error: %s", e)

# ---------------- Статусы ----------------
async def _poll_and_send(context: ContextTypes.DEFAULT_TYPE):
    global _last_hash
    cfg: Config = context.application.bot_data["cfg"]

    if not cfg.wash_ids:
        await context.bot.send_message(chat_id=cfg.group_chat_id, text="⚠️ Не задан список WASH_IDS.")
        return
    if not cfg.tms_cookie:
        await context.bot.send_message(chat_id=cfg.group_chat_id, text="⚠️ Не задан TMS_COOKIE.")
        return

    async with TMSClient(cfg.tms_base_url, cfg.tms_cookie) as tms:
        data, raw, status_code, resp_h, req_h = await tms.fetch_units(cfg.tms_project_id, cfg.wash_ids)

    text = format_washes(data, only_bad=cfg.only_bad)

    # Сырые логи — только при проблемах
    if cfg.debug_on_bad and any(is_bad_wash(w) for w in data) and cfg.debug_chat_id:
        head = json.dumps({
            "url": f"{cfg.tms_base_url}/api/v1/project/{cfg.tms_project_id}/unit/full",
            "status": status_code,
            "request_headers": redact_headers(req_h),
            "response_headers": redact_headers(resp_h),
            "request_body": cfg.wash_ids,
        }, ensure_ascii=False, indent=2)
        await _send_debug(context.bot, cfg.debug_chat_id, "TMS /unit/full (bad detected)", f"{head}\n\n{raw}")

    h = _hash_text(text)
    if h != _last_hash:
        _last_hash = h
        await context.bot.send_message(chat_id=cfg.group_chat_id, text=text)
    else:
        logger.info("No changes; skip sending.")

# ---------------- Ежедневная «выручка» (заглушка) ----------------
async def _send_daily_revenue_stub(context: ContextTypes.DEFAULT_TYPE):
    cfg: Config = context.application.bot_data["cfg"]
    chat_id = cfg.revenue_chat_id or cfg.group_chat_id
    try:
        now = datetime.now(ZoneInfo(cfg.timezone)).strftime("%Y-%m-%d %H:%M:%S %Z")
        await context.bot.send_message(chat_id=chat_id, text=f"📊 Тут будет выручка за день\n({now})")
    except Exception as e:
        logger.warning("Не удалось отправить ежедневное сообщение: %s", e)

def _seconds_until_next(hour: int, minute: int, tz_name: str) -> int:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return int((next_run - now).total_seconds())

# ---------------- Handlers ----------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Бот запущен.\n"
        "• Раз в минуту — статусы\n"
        "• Раз в день (01:00) — сообщение о выручке (заглушка)\n"
        "/status — сводка сейчас\n/whereami — chat_id"
    )
    await _poll_and_send(context)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _poll_and_send(context)

async def cmd_whereami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    await update.message.reply_text(f"chat_id: {chat.id}\nchat_type: {chat.type}\nuser_id: {user.id if user else 'n/a'}")

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error: %s", context.error)

# ---------------- Entry point ----------------
def main():
    cfg = Config.load()
    if not cfg.bot_token or not cfg.group_chat_id:
        raise RuntimeError("BOT_TOKEN/GROUP_CHAT_ID не заданы в .env")

    setup_logging(cfg.log_to_file, cfg.log_file_path)
    logger.info("Starting bot...")

    app = Application.builder().token(cfg.bot_token).build()
    app.bot_data["cfg"] = cfg

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("whereami", cmd_whereami))
    app.add_error_handler(on_error)

    if app.job_queue is None:
        raise RuntimeError("Установи extra: pip install 'python-telegram-bot[job-queue]'")

    # статусы — каждую минуту
    app.job_queue.run_repeating(_poll_and_send, interval=60, first=0, name="poll_statuses")

    # ежедневная «выручка» — эмулируем run_daily:
    # первый старт = ближайшая 01:00 в нужной TZ, далее каждые 24 часа
    if cfg.enable_daily_revenue:
        delay = _seconds_until_next(1, 0, cfg.timezone)
        app.job_queue.run_repeating(
            _send_daily_revenue_stub,
            interval=24 * 60 * 60,
            first=delay,
            name="daily_revenue_stub",
        )
        logger.info("Daily revenue stub scheduled at 01:00 %s (first in %s sec)", cfg.timezone, delay)

    app.run_polling()

if __name__ == "__main__":
    main()