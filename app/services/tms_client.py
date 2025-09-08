from __future__ import annotations
import json
import logging
from typing import Dict, List, Tuple, Optional
import httpx

logger = logging.getLogger(__name__)


class TMSClient:
    """Лёгкий async-клиент к TMS API."""

    def __init__(self, base_url: str, auth_cookie_value: str, *, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.cookie_value = auth_cookie_value
        self.timeout = timeout
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._http = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._http:
            await self._http.aclose()
            self._http = None

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Cookie": f"tms_v3_auth_cookie={self.cookie_value}",
        }

    async def fetch_units(
        self, project_id: int, ids: List[int]
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
        resp.raise_for_status()
        return resp.json(), raw_text, resp.status_code, dict(resp.headers), headers

    async def fetch_transactions(
        self,
        org_id: str,
        date_from: str,   # 'YYYY-MM-DD'
        date_to: str,     # 'YYYY-MM-DD'
        max_count: int = 1500,
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