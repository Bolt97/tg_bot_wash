# bot.py
from __future__ import annotations

import os
import json
import logging
from logging.handlers import RotatingFileHandler
from typing import List, Optional, Tuple

import httpx
from dotenv import load_dotenv
from telegram import Update, Bot
from telegram.error import BadRequest, Forbidden
from telegram.ext import Application, CommandHandler, ContextTypes

# =======================
# Конфиг из .env
# =======================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GROUP_CHAT_ID_RAW = os.getenv("GROUP_CHAT_ID", "")
TMS_COOKIE = os.getenv("TMS_COOKIE", "")  # значение из Cookie: tms_v3_auth_cookie=...
WASH_IDS = [int(x) for x in os.getenv("WASH_IDS", "").split(",") if x.strip().isdigit()]
ONLY_BAD = os.getenv("ONLY_BAD", "false").lower() in {"1", "true", "yes"}

# Диагностика/логи
DEBUG_API = os.getenv("DEBUG_API", "false").lower() in {"1", "true", "yes"}  # (не используется всегда; оставлен для совместимости)
DEBUG_ON_BAD = os.getenv("DEBUG_ON_BAD", "true").lower() in {"1", "true", "yes"}  # слать RAW только при проблемах
DEBUG_CHAT_ID_RAW = os.getenv("DEBUG_CHAT_ID", "") or GROUP_CHAT_ID_RAW
LOG_TO_FILE = os.getenv("LOG_TO_FILE", "false").lower() in {"1", "true", "yes"}
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "bot_api.log")

try:
    GROUP_CHAT_ID = int(GROUP_CHAT_ID_RAW) if GROUP_CHAT_ID_RAW else 0
except ValueError:
    GROUP_CHAT_ID = 0
try:
    DEBUG_CHAT_ID = int(DEBUG_CHAT_ID_RAW) if DEBUG_CHAT_ID_RAW else 0
except ValueError:
    DEBUG_CHAT_ID = 0

# URL ручки (POST, body = [ids...])
TMS_URL = "https://tms.termt.com/api/v1/project/29/unit/full"

# «Плохие» статусы
BAD_STATUSES = {"alarm", "error", "offline"}

# Глобальный HTTP-клиент, создаём/закрываем в lifecycle-хуках
_http: httpx.AsyncClient | None = None

# =======================
# Логирование
# =======================
logger = logging.getLogger("bot")
logger.setLevel(logging.INFO)
_console = logging.StreamHandler()
_console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(_console)
if LOG_TO_FILE:
    _rot = RotatingFileHandler(LOG_FILE_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    _rot.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_rot)

# =======================
# Утилиты
# =======================
async def _send_debug_text(bot: Bot, chat_id: int, title: str, body: str) -> None:
    """Отправляет текст; если длинно — уводит в документ .txt. Ошибки не пробрасывает."""
    if not chat_id:
        return
    MAX = 3800  # запас под <pre> и заголовок
    try:
        if len(body) <= MAX:
            await bot.send_message(
                chat_id=chat_id,
                text=f"🧪 {title}\n<pre>{body}</pre>",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        else:
            from io import BytesIO
            bio = BytesIO(body.encode("utf-8"))
            bio.name = f"{title.replace(' ', '_')}.txt"
            await bot.send_document(chat_id=chat_id, document=bio, caption=f"🧪 {title}")
    except (BadRequest, Forbidden) as e:
        logger.warning("Debug send failed to chat %s: %s", chat_id, e)
    except Exception as e:
        logger.exception("Unexpected error while sending debug to chat %s: %s", chat_id, e)

def _redact_sensitive(headers: dict[str, str]) -> dict[str, str]:
    red = dict(headers)
    if "Cookie" in red:
        red["Cookie"] = "tms_v3_auth_cookie=***REDACTED***"
    if "Authorization" in red:
        red["Authorization"] = "Bearer ***REDACTED***"
    return red

def _is_bad_wash(w: dict) -> bool:
    if (w.get("status") or {}).get("type") in BAD_STATUSES:
        return True
    for m in w.get("modules", []):
        if m.get("status") in BAD_STATUSES:
            return True
    return False

def format_washes(washes: list[dict], only_bad: bool) -> str:
    filtered = [w for w in washes if _is_bad_wash(w)] if only_bad else washes
    if only_bad and not filtered:
        return "✅ Аварийных моек не обнаружено."
    lines = []
    header = "🧽 Сводка статусов (только аварийные):" if only_bad else "🧽 Сводка статусов:"
    lines.append(header)
    for w in filtered:
        name = w.get("location_name") or f"ID {w.get('id')}"
        st = (w.get("status") or {}).get("type", "unknown")
        bad_mods = [m.get("name") for m in w.get("modules", []) if m.get("status") in BAD_STATUSES]
        if bad_mods:
            lines.append(f"• {name}: {st} (модули: {', '.join(bad_mods)})")
        else:
            lines.append(f"• {name}: {st}")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n… (обрезано)"
    return text

_last_payload_hash: str | None = None
def _hash_text(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

# =======================
# Вызов внешнего API
# =======================
async def fetch_washes(ids: List[int]) -> Tuple[list[dict], str, int, dict, dict]:
    """
    Возвращает кортеж:
      (data, raw_text, status_code, response_headers, request_headers)
    """
    assert _http is not None, "HTTP-клиент не инициализирован"
    req_headers = {
        "Content-Type": "application/json",
        "Cookie": f"tms_v3_auth_cookie={TMS_COOKIE}",
    }
    try:
        resp = await _http.post(TMS_URL, headers=req_headers, json=ids, timeout=30)
        raw_text = resp.text
        logger.info("API POST %s -> %s", TMS_URL, resp.status_code)
        resp.raise_for_status()
        data = resp.json()
        return data, raw_text, resp.status_code, dict(resp.headers), req_headers
    except httpx.HTTPError as e:
        logger.exception("HTTP error: %s", e)
        raise

# =======================
# Хэндлеры команд
# =======================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Бот запущен.\n"
        "Раз в минуту будет присылать статусы.\n"
        "Команда /status — получить сводку прямо сейчас.\n"
        "Команда /whereami — узнать текущий chat_id."
    )
    await send_statuses(context)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_statuses(context)

async def cmd_whereami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    await update.message.reply_text(
        f"chat_id: {chat.id}\nchat_type: {chat.type}\nuser_id: {user.id if user else 'n/a'}"
    )

# Глобальный ловец ошибок — чтобы не падать молча
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error with update %s: %s", update, context.error)
    if DEBUG_CHAT_ID:
        try:
            await context.bot.send_message(chat_id=DEBUG_CHAT_ID, text=f"⚠️ Unhandled error: {context.error}")
        except Exception:
            pass

# =======================
# Фоновые задачи
# =======================
async def send_statuses(context: ContextTypes.DEFAULT_TYPE):
    global _last_payload_hash

    logger.info("Polling statuses...")

    if not GROUP_CHAT_ID:
        logger.warning("GROUP_CHAT_ID is not set")
        return
    if not TMS_COOKIE:
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text="⚠️ Не задан TMS_COOKIE.")
        return
    if not WASH_IDS:
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text="⚠️ Не задан список WASH_IDS.")
        return

    try:
        data, raw_text, status_code, resp_headers, req_headers = await fetch_washes(WASH_IDS)

        # обычная сводка
        text = format_washes(data, only_bad=ONLY_BAD)

        # есть ли «плохие» статусы?
        bad_present = any(_is_bad_wash(w) for w in data)

        # если обнаружены проблемы — шлём сырые логи (если включено и есть чат)
        if DEBUG_ON_BAD and bad_present and DEBUG_CHAT_ID:
            meta = {
                "url": TMS_URL,
                "status": status_code,
                "request_headers": _redact_sensitive(req_headers),
                "response_headers": _redact_sensitive(resp_headers),
                "request_body": WASH_IDS,
            }
            head = json.dumps(meta, ensure_ascii=False, indent=2)
            await _send_debug_text(context.bot, DEBUG_CHAT_ID, "TMS /unit/full (bad detected)", f"{head}\n\n{raw_text}")

        # не спамим одинаковым
        h = _hash_text(text)
        if h != _last_payload_hash:
            _last_payload_hash = h
            await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=text)
        else:
            logger.info("No changes in summary; skip sending.")

    except httpx.HTTPError as e:
        await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=f"⚠️ Ошибка запроса статусов: {e}")

# =======================
# Lifecycle-хуки приложения
# =======================
async def on_startup(app: Application):
    global _http
    _http = httpx.AsyncClient()
    logger.info("HTTP client initialized")

async def on_shutdown(app: Application):
    global _http
    if _http:
        await _http.aclose()
        _http = None
        logger.info("HTTP client closed")

# =======================
# Точка входа
# =======================
def main():
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not GROUP_CHAT_ID:
        missing.append("GROUP_CHAT_ID")
    if missing:
        raise RuntimeError(f"Не заданы переменные окружения: {', '.join(missing)}")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("whereami", cmd_whereami))
    app.add_error_handler(on_error)

    # Планировщик (extra: pip install 'python-telegram-bot[job-queue]')
    if app.job_queue is None:
        raise RuntimeError("Нужен extra: pip install 'python-telegram-bot[job-queue]'")

    app.job_queue.run_repeating(send_statuses, interval=60, first=0, name="poll_statuses")

    app.run_polling()

if __name__ == "__main__":
    main()