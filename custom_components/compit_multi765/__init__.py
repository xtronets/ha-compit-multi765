"""Compit MULTI 765 (iNext) – odczyt, bezpieczny zapis nastaw i sterowanie pogodowe.

Ta wersja niczego nie zapisuje do sterownika. Pobiera pełny stan urządzenia
z API mobilnego iNext co 2 minuty i udostępnia go jako jeden sensor
diagnostyczny oraz usługę zrzutu do pliku /config/compit_multi765_dump.json.
"""

from __future__ import annotations

from datetime import timedelta
import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers.event import async_call_later

import time

import aiohttp
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import CompitApi, CompitAuthError, CompitError
from .const import (
    CONF_DEVICE_ID,
    DOMAIN,
    DUMP_FILENAME,
    FULL_READ_WAIT_S,
    FULL_STATE_INTERVAL_S,
    MIN_CYCLE_GAP_S,
    NUMBERS,
    SWITCHES,
    REFRESH_AFTER_WRITE_S,
    SCAN_INTERVAL_SECONDS,
)
from .weather import WeatherControl
from .web import CompitFullState

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.NUMBER, Platform.BUTTON, Platform.SWITCH]


class CompitCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Łączy stan podstawowy (API mobilne, co 2 min) z pełnym stanem (co 10 min)."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: CompitApi,
        device_id: int,
        full: CompitFullState | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device_id}",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.api = api
        self.device_id = device_id
        self.full = full
        self._full_params: dict[str, dict[str, Any]] = {}
        self._full_meta: dict[str, Any] = {}
        self._full_ts: float = 0.0
        self._force_full = True
        self._base_codes: set[str] = set()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            state = await self.api.get_state(self.device_id)
        except CompitAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except CompitError as err:
            raise UpdateFailed(str(err)) from err

        if self.full is not None and (
            self._force_full or time.monotonic() - self._full_ts > FULL_STATE_INTERVAL_S
        ):
            try:
                full = await self.full.get_full_state()
                self._full_params = {
                    p["code"]: p for p in full.get("params", []) if p and "code" in p
                }
                self._full_meta = {"last_full_update_at": full.get("last_full_update_at")}
                self._full_ts = time.monotonic()
                self._force_full = False
            except CompitError as err:
                # Pełny stan jest dodatkiem – jego brak nie wyłącza integracji.
                _LOGGER.warning("Compit MULTI765: pełny stan niedostępny: %s", err)

        base = [p for p in state.get("params", []) if p and "code" in p]
        self._base_codes = {p["code"] for p in base}
        merged = dict(self._full_params)
        for p in base:  # stan podstawowy jest świeższy – nadpisuje kopię pełną
            merged[p["code"]] = p
        return {
            **state,
            **self._full_meta,
            "full_mode": self.full.mode if self.full else None,
            "params": list(merged.values()),
        }

    async def async_controller_read(self) -> None:
        """„Pobierz grupę”: bramka czyta parametry ze sterownika, potem odświeżamy."""
        if self.full is None:
            raise HomeAssistantError("Pełny stan niedostępny")
        try:
            await self.full.request_controller_read()
        except CompitError as err:
            raise HomeAssistantError(str(err)) from err
        for delay in FULL_READ_WAIT_S:
            async_call_later(self.hass, delay, self._delayed_full_refresh)

    async def _delayed_full_refresh(self, _now: Any) -> None:
        self._force_full = True
        await self.async_request_refresh()

    def param(self, code: str) -> dict[str, Any] | None:
        """Zwraca słownik parametru o danym kodzie (albo None)."""
        for p in (self.data or {}).get("params", []):
            if p and p.get("code") == code:
                return p
        return None

    def value(self, code: str) -> Any:
        p = self.param(code)
        return None if p is None else p.get("value")

    def _validate(self, code: str, value: float) -> None:
        """Sprawdza zakres i reguły DTR. Rzuca HomeAssistantError, gdy zapis jest niebezpieczny."""
        spec = NUMBERS.get(code) or SWITCHES.get(code)
        if spec is None:
            raise HomeAssistantError(f"Parametr {code} nie jest dopuszczony do zapisu")
        if not spec["min"] <= value <= spec["max"]:
            raise HomeAssistantError(
                f"{code}: wartość {value} poza bezpiecznym zakresem {spec['min']}–{spec['max']}"
            )
        p = self.param(code)
        if p is None or not p.get("write"):
            raise HomeAssistantError(f"Sterownik nie pozwala zapisać {code}")

        def other(c: str) -> float:
            v = self.value(c)
            if v is None:
                raise HomeAssistantError(f"Brak aktualnej wartości {c} – zapis wstrzymany")
            return float(v)

        if code == "__pidwentylatorpmax" and value <= other("__pidwentylatorpmin"):
            raise HomeAssistantError("Obroty went. Pmax muszą być wyższe niż Pmin (DTR)")
        if code == "__pidwentylatorpmin" and value >= other("__pidwentylatorpmax"):
            raise HomeAssistantError("Obroty went. Pmin muszą być niższe niż Pmax (DTR)")
        if code == "__pidczascyklu" and value + MIN_CYCLE_GAP_S > other("__pidczascyklumin"):
            raise HomeAssistantError(
                f"Czas cyklu Pmax musi być krótszy od Pmin o min. {MIN_CYCLE_GAP_S} s (DTR)"
            )
        if code == "__pidczascyklumin" and value - MIN_CYCLE_GAP_S < other("__pidczascyklu"):
            raise HomeAssistantError(
                f"Czas cyklu Pmin musi być dłuższy od Pmax o min. {MIN_CYCLE_GAP_S} s (DTR)"
            )
        if code == "__obrotywent2mocmax" and value <= other("__pidobrotywent2mocmin"):
            raise HomeAssistantError("Obroty went. 2 Pmax muszą być wyższe niż Pmin (DTR)")
        if code == "__pidobrotywent2mocmin" and value >= other("__obrotywent2mocmax"):
            raise HomeAssistantError("Obroty went. 2 Pmin muszą być niższe niż Pmax (DTR)")

    async def async_write(self, code: str, value: float) -> None:
        """Bezpieczny zapis: walidacja → PUT → lokalna aktualizacja → odświeżenie po chwili."""
        value = int(round(value))
        self._validate(code, value)
        if self.value(code) == value:
            return
        old = self.value(code)
        try:
            if code in self._base_codes or self.full is None:
                await self.api.set_parameter(self.device_id, code, value)
            else:
                await self.full.set_parameter(code, value)
        except CompitError as err:
            raise HomeAssistantError(str(err)) from err
        if code not in self._base_codes:
            self._force_full = True

        self.hass.bus.async_fire(
            f"{DOMAIN}_parameter_set",
            {"device_id": self.device_id, "code": code, "old": old, "new": value},
        )
        p = self.param(code)
        if p is not None:
            p["value"] = value
        self.async_set_updated_data(self.data)

        for delay in REFRESH_AFTER_WRITE_S:
            async_call_later(self.hass, delay, self._delayed_refresh)

    async def _delayed_refresh(self, _now: Any) -> None:
        await self.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = CompitApi(
        async_get_clientsession(hass),
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
    )
    device_id = entry.data[CONF_DEVICE_ID]
    full: CompitFullState | None = None
    try:
        await api.authenticate()
    except CompitAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except CompitError as err:
        raise ConfigEntryNotReady(str(err)) from err
    try:
        gates = await api.get_gates()
        for gate in gates.get("gates", []):
            if any(d.get("id") == device_id for d in gate.get("devices", [])):
                web_session = async_create_clientsession(
                    hass, cookie_jar=aiohttp.CookieJar()
                )
                full = CompitFullState(
                    api,
                    web_session,
                    entry.data[CONF_EMAIL],
                    entry.data[CONF_PASSWORD],
                    gate_id=gate["id"],
                    gate_code=gate["code"],
                    device_id=device_id,
                )
                break
        if full is not None:
            await full.detect()
    except CompitError as err:
        _LOGGER.warning("Compit MULTI765: pełny stan wyłączony: %s", err)
        full = None

    coordinator = CompitCoordinator(hass, api, device_id, full)
    await coordinator.async_config_entry_first_refresh()
    coordinator.weather = WeatherControl(hass, coordinator, dict(entry.options))
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.weather.async_start()
    entry.async_on_unload(coordinator.weather.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    async def handle_dump(call: ServiceCall) -> dict[str, Any]:
        """Zapisuje pełną odpowiedź API (bramki + stan) do pliku w /config."""
        gates = await api.get_gates()
        state = await api.get_state(coordinator.device_id)
        dump = {
            "created": dt_util.now().isoformat(),
            "device_id": coordinator.device_id,
            "gates": gates.get("gates", gates) if isinstance(gates, dict) else gates,
            "state": state,
        }
        path = hass.config.path(DUMP_FILENAME)

        def _write() -> None:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(dump, fh, ensure_ascii=False, indent=2)

        await hass.async_add_executor_job(_write)
        params = state.get("params", []) if isinstance(state, dict) else []
        _LOGGER.warning(
            "Compit MULTI765: zapisano %d parametrów do %s", len(params), path
        )
        return {"file": path, "params": len(params)}

    if not hass.services.has_service(DOMAIN, "dump_parameters"):
        hass.services.async_register(
            DOMAIN,
            "dump_parameters",
            handle_dump,
            supports_response=SupportsResponse.OPTIONAL,
        )
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and not hass.config_entries.async_loaded_entries(DOMAIN):
        hass.services.async_remove(DOMAIN, "dump_parameters")
    return unloaded
