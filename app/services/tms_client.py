from __future__ import annotations
import json
import logging
from typing import Dict, List, Tuple, Optional, Callable, Awaitable
import httpx

logger = logging.getLogger(__name__)


class TMSClient:
    """Лёгкий async-клиент к TMS API с автообновлением токена."""

    def __init__(
        self,
        base_url: str,
        *,
        email: str,
        password: str,
        on_token_refresh: Callable[[str], Awaitable[None]] | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._email = email
        self._password = password
        self._on_token_refresh = on_token_refresh
        self.timeout = timeout
        self.cookie_value: str = ""
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._http = httpx.AsyncClient(timeout=self.timeout)
        # Получаем токен при старте
        await self._ensure_token()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._http:
            await self._http.aclose()
            self._http = None

    async def _ensure_token(self) -> None:
        """Получить токен, если его ещё нет."""
        if not self.cookie_value:
            self.cookie_value = await self.sign_in()
            logger.info("TMS token obtained via sign_in")

    async def sign_in(self) -> str:
        """
        POST /api/v1/sign-in с JSON body.
        Возвращает новый cookie value.
        """
        assert self._http is not None
        url = f"{self.base_url}/api/v1/sign-in"
        payload = {"email": self._email, "password": self._password}
        resp = await self._http.post(url, json=payload)
        logger.info("TMS sign-in %s -> %s", url, resp.status_code)
        resp.raise_for_status()
        # Извлечь cookie из response
        new_cookie = resp.cookies.get("tms_v3_auth_cookie")
        if not new_cookie:
            raise ValueError("sign_in не вернул tms_v3_auth_cookie")
        return new_cookie

    async def _refresh_token(self) -> None:
        """Обновить токен и вызвать callback."""
        logger.warning("Refreshing TMS token...")
        self.cookie_value = await self.sign_in()
        if self._on_token_refresh:
            await self._on_token_refresh("Токен TMS обновлён")

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Cookie": f"tms_v3_auth_cookie={self.cookie_value}",
        }

    async def fetch_units(
        self, project_id: int, ids: List[int], *, _retried: bool = False
    ) -> Tuple[list[dict], str, int, Dict[str, str], Dict[str, str]]:
        """
        POST /api/v1/project/{project_id}/unit/full
        Body: [ids...]
        Возвращает (data, raw_text, status_code, response_headers, request_headers)
        """
        assert self._http is not None
        url = f"{self.base_url}/api/v1/project/{project_id}/unit/full"
        headers = self._headers()
        resp = await self._http.post(url, headers=headers, json=ids)
        raw_text = resp.text
        logger.info("TMS %s -> %s", url, resp.status_code)

        # При 401 пробуем обновить токен и повторить запрос
        if resp.status_code == 401 and not _retried:
            await self._refresh_token()
            return await self.fetch_units(project_id, ids, _retried=True)

        resp.raise_for_status()
        return resp.json(), raw_text, resp.status_code, dict(resp.headers), headers

    async def fetch_transactions(
        self,
        org_id: str,
        date_from: str,   # 'YYYY-MM-DD'
        date_to: str,     # 'YYYY-MM-DD'
        max_count: int = 1500,
        *,
        _retried: bool = False,
    ) -> Tuple[dict, str, int, Dict[str, str], Dict[str, str]]:
        """
        GET /api/v1/org/{org_id}/transactions?from=...&to=...&max-count=...&next-id=...
        Собирает все страницы (пока next_id != null). Возвращает объединённый JSON.
        """
        assert self._http is not None
        headers = self._headers()
        base = f"{self.base_url}/api/v1/org/{org_id}/transactions"

        all_items: List[dict] = []
        next_id: Optional[str] = None
        last_status = 0
        last_resp_headers: Dict[str, str] = {}

        # Пагинация
        while True:
            params = {
                "from": date_from,
                "to": date_to,
                "max-count": str(max_count),
            }
            if next_id:
                params["next-id"] = next_id

            resp = await self._http.get(base, headers=headers, params=params)
            last_status = resp.status_code
            last_resp_headers = dict(resp.headers)
            logger.info("TMS %s -> %s", resp.request.url, resp.status_code)

            # При 401 пробуем обновить токен и повторить запрос
            if resp.status_code == 401 and not _retried:
                await self._refresh_token()
                return await self.fetch_transactions(
                    org_id, date_from, date_to, max_count, _retried=True
                )

            resp.raise_for_status()

            data = resp.json()
            page_items = data.get("items", []) if isinstance(data, dict) else []
            all_items.extend(page_items)
            next_id = data.get("next_id")

            if not next_id:
                break

        combined = {"items": all_items, "next_id": None}
        raw_text = json.dumps(combined, ensure_ascii=False)
        return combined, raw_text, last_status, last_resp_headers, headers


def redact_headers(h: Dict[str, str]) -> Dict[str, str]:
    r = dict(h)
    if "Cookie" in r:
        r["Cookie"] = "tms_v3_auth_cookie=***REDACTED***"
    if "Authorization" in r:
        r["Authorization"] = "Bearer ***REDACTED***"
    return r