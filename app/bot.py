# app/bot.py
import logging
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from zoneinfo import ZoneInfo

from .config import load_config
from .tasks.statuses import send_statuses
from .tasks.revenue import send_daily_revenue_stub

logger = logging.getLogger(__name__)

cfg = load_config()


async def cmd_status_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status_bot — проверка, жив ли бот"""
    jobs = context.job_queue.jobs()
    jobs_info = "\n".join([f"- {j.name} (next: {j.next_t})" for j in jobs]) or "Нет активных задач"

    text = (
        "🤖 Бот работает!\n\n"
        f"Запущенные задачи:\n{jobs_info}"
    )
    await update.message.reply_text(text)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info("Starting bot...")

    app = (
        ApplicationBuilder()
        .token(cfg.bot_token)
        .build()
    )

    # команды
    app.add_handler(CommandHandler("status_bot", cmd_status_bot))

    # периодические задачи
    app.job_queue.run_repeating(
        send_statuses,
        interval=300,  # 5 минут
        first=5,
        name="send_statuses",
    )

    app.job_queue.run_daily(
        send_daily_revenue_stub,
        time=asyncio.time(0, 0),  # каждый день в 00:00
        name="daily_revenue",
        # Если версия telegram не поддерживает tzinfo, оставим без него
        # tzinfo=ZoneInfo(cfg.timezone),
    )

    app.run_polling()


if __name__ == "__main__":
    main()