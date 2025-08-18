from __future__ import annotations
import logging
from typing import Dict, List, Tuple
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

    async def fetch_units(self, project_id: int, ids: List[int]) -> Tuple[list[dict], str, int, Dict[str, str], Dict[str, str]]:
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

def redact_headers(h: Dict[str, str]) -> Dict[str, str]:
    r = dict(h)
    if "Cookie" in r:
        r["Cookie"] = "tms_v3_auth_cookie=***REDACTED***"
    if "Authorization" in r:
        r["Authorization"] = "Bearer ***REDACTED***"
    return r