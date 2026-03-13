import httpx
from typing import Optional, Any
from app.config import settings

TIMEOUT = 30.0


class SMSBowerClient:
    def __init__(self):
        self.base_url = settings.SMSBOWER_BASE_URL

    async def _request(self, params: dict) -> Any:
        params["api_key"] = settings.SMSBOWER_API_KEY
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(self.base_url, params=params)
            resp.raise_for_status()
            if "application/json" in resp.headers.get("content-type", ""):
                return resp.json()
            return resp.text

    async def get_balance(self) -> str:
        return await self._request({"action": "getBalance"})

    async def get_services(self, country: Optional[str] = None) -> Any:
        params = {"action": "getServices"}
        if country:
            params["country"] = country
        return await self._request(params)

    async def get_number(self, service: str, country: str = "0") -> str:
        return await self._request({"action": "getNumber", "service": service, "country": country})

    async def get_status(self, activation_id: str) -> str:
        return await self._request({"action": "getStatus", "id": activation_id})

    async def set_status(self, activation_id: str, status: str) -> str:
        return await self._request({"action": "setStatus", "id": activation_id, "status": status})

    async def health_check(self) -> dict:
        try:
            balance = await self.get_balance()
            return {"status": "ok", "source_balance": balance}
        except Exception as e:
            return {"status": "error", "error": str(e)}


smsbower_client = SMSBowerClient()
