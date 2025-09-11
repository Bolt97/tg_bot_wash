from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _as_bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(env_name: str, default: int = 0) -> int:
    """Безопасно читаем int из .env: обрезаем пробелы, пустое -> default."""
    raw = os.getenv(env_name)
    if raw is None:
        return default
    raw = raw.strip()
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        # Дадим явную ошибку, чтобы было видно, что в .env мусор
        raise ValueError(f"Invalid integer for {env_name}: {raw!r}")


@dataclass(frozen=True)
class Config:
    # Telegram
    bot_token: str
    group_chat_id: int
    debug_chat_id: int

    # Мониторинг статусов
    only_bad: bool
    debug_on_bad: bool

    # Логи
    log_to_file: bool
    log_file_path: str

    # TMS
    tms_cookie: str
    tms_base_url: str
    tms_project_id: int
    wash_ids: list[int]
    org_id: str  # org id, например "o3238"

    # Ежедневная выручка
    enable_daily_revenue: bool
    timezone: str
    revenue_chat_id: int

    @staticmethod
    def load() -> "Config":
        # Telegram
        bot_token = (os.getenv("BOT_TOKEN") or "").strip()
        group_chat_id = _as_int("GROUP_CHAT_ID", 0)
        debug_chat_id = _as_int("DEBUG_CHAT_ID", group_chat_id or 0)

        # Мониторинг
        only_bad = _as_bool(os.getenv("ONLY_BAD"), True)
        debug_on_bad = _as_bool(os.getenv("DEBUG_ON_BAD"), True)

        # Логи
        log_to_file = _as_bool(os.getenv("LOG_TO_FILE"), True)
        log_file_path = (os.getenv("LOG_FILE_PATH") or "bot_api.log").strip()

        # TMS
        tms_cookie = (os.getenv("TMS_COOKIE") or "").strip()
        tms_base_url = (os.getenv("TMS_BASE_URL") or "https://tms.termt.com").strip()
        tms_project_id = _as_int("TMS_PROJECT_ID", 29)

        # список ID моек
        raw_wash_ids = os.getenv("WASH_IDS", "")
        wash_ids = []
        for x in raw_wash_ids.split(","):
            x = x.strip()
            if x.isdigit():
                wash_ids.append(int(x))

        org_id = (os.getenv("TMS_ORG_ID") or "").strip()

        # Выручка
        enable_daily_revenue = _as_bool(os.getenv("ENABLE_DAILY_REVENUE"), True)
        timezone = (os.getenv("TIMEZONE") or "Europe/Berlin").split("#", 1)[0].strip()
        # ВАЖНО: если REVENUE_CHAT_ID пустой/битый — используем group_chat_id
        revenue_chat_id = _as_int("REVENUE_CHAT_ID", group_chat_id or 0)

        cfg = Config(
            bot_token=bot_token,
            group_chat_id=group_chat_id,
            debug_chat_id=debug_chat_id,
            only_bad=only_bad,
            debug_on_bad=debug_on_bad,
            log_to_file=log_to_file,
            log_file_path=log_file_path,
            tms_cookie=tms_cookie,
            tms_base_url=tms_base_url,
            tms_project_id=tms_project_id,
            wash_ids=wash_ids,
            org_id=org_id,
            enable_daily_revenue=enable_daily_revenue,
            timezone=timezone,
            revenue_chat_id=revenue_chat_id,
        )

        # Небольшая диагностика при старте — один раз в лог
        import logging
        logger = logging.getLogger(__name__)
        logger.info(
            "CFG: GROUP_CHAT_ID=%s, REVENUE_CHAT_ID=%s, TIMEZONE=%s, ORG=%s, WASH_IDS=%s",
            cfg.group_chat_id, cfg.revenue_chat_id, cfg.timezone, cfg.org_id, cfg.wash_ids
        )

        return cfg