import os
import httpx
from typing import List

TMS_COOKIE = os.getenv("TMS_COOKIE")

async def fetch_washes(ids: List[int]) -> list[dict]:
    """
    Получить статусы моек по списку ID.
    """
    url = "https://tms.termt.com/api/v1/project/29/unit/full"
    headers = {
        "Content-Type": "application/json",
        "Cookie": f"tms_v3_auth_cookie={TMS_COOKIE}",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, json=ids, timeout=30)
        resp.raise_for_status()
        return resp.json()