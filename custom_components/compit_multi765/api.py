"""Minimalny klient API mobilnego Compit iNext (etap 0: tylko odczyt)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import API_URL, CLIENT_LABEL, CLIENT_UID

_LOGGER = logging.getLogger(__name__)
TIMEOUT = 15


class CompitError(Exception):
    """Ogólny błąd API."""


class CompitAuthError(CompitError):
    """Błędny login lub hasło."""


class CompitConnectionError(CompitError):
    """Brak połączenia z chmurą Compit."""


class CompitApi:
    """Klient API mobilnego iNext."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._token: str | None = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        form: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> aiohttp.ClientResponse:
        headers: dict[str, str] = {}
        if auth and self._token:
            headers["Authorization"] = self._token
        try:
            async with asyncio.timeout(TIMEOUT):
                resp = await self._session.request(
                    method, f"{API_URL}{path}", data=form, headers=headers
                )
                await resp.read()
                return resp
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CompitConnectionError(str(err)) from err

    async def authenticate(self) -> dict[str, Any]:
        """Loguje się i zwraca listę bramek z urządzeniami."""
        creds = {
            "email": self._email,
            "password": self._password,
            "uid": CLIENT_UID,
            "label": CLIENT_LABEL,
        }
        for _ in range(2):
            resp = await self._request("post", "/authorize", form=creds, auth=False)
            if resp.status == 401:
                raise CompitAuthError("Nieprawidłowy e-mail lub hasło")
            if resp.status == 422:
                # Konto zna użytkownika, ale ten klient (uid) nie jest jeszcze
                # zarejestrowany – rejestrujemy go i ponawiamy logowanie.
                body = await resp.json(content_type=None)
                self._token = body.get("token")
                reg = await self._request(
                    "post",
                    "/clients",
                    form={"fcm_token": "", "uid": CLIENT_UID, "label": CLIENT_LABEL},
                )
                if reg.status >= 400:
                    raise CompitError(f"Rejestracja klienta nieudana: HTTP {reg.status}")
                continue
            if resp.status >= 400:
                raise CompitError(f"Logowanie nieudane: HTTP {resp.status}")
            body = await resp.json(content_type=None)
            self._token = body.get("token")
            if not self._token:
                raise CompitError("Brak tokenu w odpowiedzi logowania")
            return body
        raise CompitError("Nie udało się zalogować po rejestracji klienta")

    async def _get_json(self, path: str) -> Any:
        if not self._token:
            await self.authenticate()
        resp = await self._request("get", path)
        if resp.status == 401:
            # Token wygasł – logujemy się ponownie i powtarzamy zapytanie.
            await self.authenticate()
            resp = await self._request("get", path)
        if resp.status >= 400:
            raise CompitError(f"GET {path}: HTTP {resp.status}")
        return await resp.json(content_type=None)

    async def get_gates(self) -> Any:
        """Bramki i urządzenia na koncie."""
        return await self._get_json("/gates")

    async def get_state(self, device_id: int) -> Any:
        """Pełny stan urządzenia: wszystkie parametry z min/max i flagą zapisu."""
        return await self._get_json(f"/devices/{device_id}/state")

    async def _put_json(self, path: str, payload: dict[str, Any]) -> aiohttp.ClientResponse:
        headers = {"Authorization": self._token or ""}
        try:
            async with asyncio.timeout(TIMEOUT):
                resp = await self._session.put(f"{API_URL}{path}", json=payload, headers=headers)
                await resp.read()
                return resp
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CompitConnectionError(str(err)) from err

    async def set_parameter(self, device_id: int, code: str, value: Any) -> Any:
        """Zapisuje jeden parametr sterownika (PUT /devices/{id}/params)."""
        if not self._token:
            await self.authenticate()
        payload = {"values": [{"code": code, "value": value}]}
        path = f"/devices/{device_id}/params"
        resp = await self._put_json(path, payload)
        if resp.status == 401:
            await self.authenticate()
            resp = await self._put_json(path, payload)
        if resp.status >= 400:
            text = await resp.text()
            raise CompitError(f"Zapis {code}={value} nieudany: HTTP {resp.status} {text[:200]}")
        _LOGGER.warning("Compit MULTI765: zapisano %s = %s", code, value)
        try:
            return await resp.json(content_type=None)
        except ValueError:
            return None
