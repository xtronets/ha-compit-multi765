"""Pełny stan sterownika (wszystkie ~119 parametrów, także serwisowe).

API mobilne zwraca tylko podstawowe 36 parametrów. Pełny zestaw udostępnia panel WWW:
  GET  /api/gates/{gate_id}/devices/{id}/full_state   – odczyt
  POST /api/gates/{gate_code}/devices/{id}/full        – „Pobierz grupę” (odczyt ze sterownika)
  PUT  /api/gates/{gate_id}/devices/{id}/params        – zapis {"values":[{"code","value"}]}
Panel loguje się formularzem (/pl/login + _csrf_token), a potem używa tokena Bearer
z <meta id="token">. Najpierw próbujemy tych samych ścieżek w API mobilnym (stabilniejsze
logowanie), a dopiero gdy ich tam nie ma – logujemy się jak przeglądarka.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import aiohttp

from .api import CompitApi, CompitAuthError, CompitConnectionError, CompitError
from .const import API_URL

_LOGGER = logging.getLogger(__name__)
WEB_URL = "https://inext.compit.pl"
TIMEOUT = 20

_CSRF_RE = re.compile(r'name="_csrf_token"[^>]*value="([^"]+)"')
_TOKEN_RE = re.compile(r'id="token"[^>]*content="([^"]+)"|content="([^"]+)"[^>]*id="token"')


class CompitFullState:
    """Odczyt / zapis pełnego zestawu parametrów (tryb 'mobile' albo 'web')."""

    def __init__(
        self,
        mobile: CompitApi,
        web_session: aiohttp.ClientSession,
        email: str,
        password: str,
        gate_id: int,
        gate_code: str,
        device_id: int,
    ) -> None:
        self._mobile = mobile
        self._web = web_session
        self._email = email
        self._password = password
        self.gate_id = gate_id
        self.gate_code = gate_code
        self.device_id = device_id
        self.mode: str | None = None  # "mobile" | "web"
        self._mobile_path: str | None = None
        self._bearer: str | None = None

    # ---------- wykrywanie ----------
    async def detect(self) -> str:
        """Ustala, skąd brać pełny stan. Zwraca 'mobile' albo 'web'."""
        for path in (
            f"/gates/{self.gate_id}/devices/{self.device_id}/full_state",
            f"/devices/{self.device_id}/full_state",
        ):
            try:
                data = await self._mobile._get_json(path)  # noqa: SLF001
            except CompitError:
                continue
            if isinstance(data, dict) and isinstance(data.get("params"), list) and len(data["params"]) > 40:
                self.mode, self._mobile_path = "mobile", path
                _LOGGER.warning("Compit MULTI765: pełny stan z API mobilnego (%s)", path)
                return self.mode
        await self._web_login()
        self.mode = "web"
        _LOGGER.warning("Compit MULTI765: pełny stan z API panelu WWW")
        return self.mode

    # ---------- logowanie WWW ----------
    async def _web_login(self) -> None:
        try:
            async with asyncio.timeout(TIMEOUT):
                async with self._web.get(f"{WEB_URL}/pl/login") as resp:
                    html = await resp.text()
                m = _CSRF_RE.search(html)
                if not m:
                    raise CompitError("Brak _csrf_token na stronie logowania")
                form = {
                    "_csrf_token": m.group(1),
                    "email": self._email,
                    "password": self._password,
                }
                async with self._web.post(f"{WEB_URL}/pl/login", data=form) as resp:
                    await resp.read()
                async with self._web.get(f"{WEB_URL}/pl") as resp:
                    html = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CompitConnectionError(str(err)) from err
        m = _TOKEN_RE.search(html)
        if not m:
            raise CompitAuthError("Logowanie do panelu WWW nieudane (brak tokenu)")
        self._bearer = m.group(1) or m.group(2)

    async def _web_request(self, method: str, path: str, json: Any = None) -> Any:
        if not self._bearer:
            await self._web_login()
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {self._bearer}", "Accept": "application/json"}
            try:
                async with asyncio.timeout(TIMEOUT):
                    async with self._web.request(
                        method, f"{WEB_URL}{path}", json=json, headers=headers
                    ) as resp:
                        status = resp.status
                        body = await resp.text()
            except (aiohttp.ClientError, TimeoutError) as err:
                raise CompitConnectionError(str(err)) from err
            if status == 401 and attempt == 0:
                await self._web_login()
                continue
            if status >= 400:
                raise CompitError(f"{method} {path}: HTTP {status} {body[:200]}")
            try:
                import json as _json

                return _json.loads(body) if body else None
            except ValueError:
                return body
        raise CompitError(f"{method} {path}: brak autoryzacji")

    # ---------- operacje ----------
    async def get_full_state(self) -> dict[str, Any]:
        if self.mode is None:
            await self.detect()
        if self.mode == "mobile":
            return await self._mobile._get_json(self._mobile_path)  # noqa: SLF001
        return await self._web_request(
            "GET", f"/api/gates/{self.gate_id}/devices/{self.device_id}/full_state"
        )

    async def request_controller_read(self) -> None:
        """Odpowiednik „Pobierz grupę” – bramka czyta wszystkie parametry ze sterownika."""
        if self.mode is None:
            await self.detect()
        if self.mode == "mobile":
            for path in (
                f"/gates/{self.gate_code}/devices/{self.device_id}/full",
                f"/devices/{self.device_id}/full",
            ):
                resp = await self._mobile._request("post", path)  # noqa: SLF001
                if resp.status < 400:
                    return
        await self._web_request("POST", f"/api/gates/{self.gate_code}/devices/{self.device_id}/full")

    async def set_parameter(self, code: str, value: Any) -> Any:
        """Zapis parametru spoza podstawowego zestawu."""
        if self.mode is None:
            await self.detect()
        if self.mode == "mobile":
            return await self._mobile.set_parameter(self.device_id, code, value)
        result = await self._web_request(
            "PUT",
            f"/api/gates/{self.gate_id}/devices/{self.device_id}/params",
            json={"values": [{"code": code, "value": value}]},
        )
        _LOGGER.warning("Compit MULTI765: zapisano (WWW) %s = %s", code, value)
        return result


__all__ = ["CompitFullState", "API_URL"]
