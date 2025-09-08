from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _as_bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


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
    org_id: str  # добавили org_id

    # Ежедневное сообщение «выручка»: 01:00 по TZ
    enable_daily_revenue: bool
    timezone: str
    revenue_chat_id: int

    @staticmethod
    def load() -> "Config":
        bot_token = os.getenv("BOT_TOKEN", "")
        group_chat_id = int(os.getenv("GROUP_CHAT_ID", "0") or "0")
        debug_chat_id = int(os.getenv("DEBUG_CHAT_ID", str(group_chat_id or 0)) or "0")

        only_bad = _as_bool(os.getenv("ONLY_BAD"), True)
        debug_on_bad = _as_bool(os.getenv("DEBUG_ON_BAD"), True)

        log_to_file = _as_bool(os.getenv("LOG_TO_FILE"), True)
        log_file_path = os.getenv("LOG_FILE_PATH", "bot_api.log")

        tms_cookie = os.getenv("TMS_COOKIE", "")
        tms_base_url = os.getenv("TMS_BASE_URL", "https://tms.termt.com")
        tms_project_id = int(os.getenv("TMS_PROJECT_ID", "29") or "29")
        wash_ids = [int(x) for x in os.getenv("WASH_IDS", "").split(",") if x.strip().isdigit()]
        org_id = os.getenv("TMS_ORG_ID", "")  # новый параметр

        enable_daily_revenue = _as_bool(os.getenv("ENABLE_DAILY_REVENUE"), True)
        timezone = os.getenv("TIMEZONE", "Europe/Berlin")
        revenue_chat_id = int(os.getenv("REVENUE_CHAT_ID", str(group_chat_id or 0)) or "0")

        return Config(
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