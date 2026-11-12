"""Konfiguracja z UI: logowanie do iNext i wybór sterownika."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CompitApi, CompitAuthError, CompitConnectionError, CompitError
from .const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_LABEL,
    CONF_W_CLIMATES,
    CONF_W_FALLBACK,
    CONF_W_OUTDOOR,
    CONF_W_SETBACK,
    DEFAULT_W_OPTIONS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class CompitMulti765ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Kreator dodania integracji."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return CompitOptionsFlow()

    def __init__(self) -> None:
        self._email: str | None = None
        self._password: str | None = None
        self._devices: dict[str, str] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api = CompitApi(
                async_get_clientsession(self.hass),
                user_input[CONF_EMAIL],
                user_input[CONF_PASSWORD],
            )
            try:
                await api.authenticate()
                gates = await api.get_gates()
            except CompitAuthError:
                errors["base"] = "invalid_auth"
            except CompitConnectionError:
                errors["base"] = "cannot_connect"
            except CompitError:
                _LOGGER.exception("Błąd API Compit")
                errors["base"] = "unknown"
            else:
                self._email = user_input[CONF_EMAIL]
                self._password = user_input[CONF_PASSWORD]
                for gate in gates.get("gates", []):
                    for dev in gate.get("devices", []):
                        label = f"{dev.get('label')} (bramka {gate.get('code')}, id {dev.get('id')}, typ {dev.get('type')})"
                        self._devices[str(dev["id"])] = label
                if not self._devices:
                    errors["base"] = "no_devices"
                else:
                    return await self.async_step_device()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Hasło do iNext zostało zmienione – poproś o nowe dane."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            api = CompitApi(
                async_get_clientsession(self.hass),
                user_input[CONF_EMAIL],
                user_input[CONF_PASSWORD],
            )
            try:
                await api.authenticate()
            except CompitAuthError:
                errors["base"] = "invalid_auth"
            except CompitConnectionError:
                errors["base"] = "cannot_connect"
            except CompitError:
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=entry.data.get(CONF_EMAIL)): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            await self.async_set_unique_id(f"compit_multi765_{device_id}")
            self._abort_if_unique_id_configured()
            label = self._devices[device_id]
            return self.async_create_entry(
                title=label.split(" (")[0],
                data={
                    CONF_EMAIL: self._email,
                    CONF_PASSWORD: self._password,
                    CONF_DEVICE_ID: int(device_id),
                    CONF_DEVICE_LABEL: label,
                },
            )

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {vol.Required(CONF_DEVICE_ID): vol.In(self._devices)}
            ),
        )


class CompitOptionsFlow(OptionsFlow):
    """Opcje sterowania pogodowego: czujniki, harmonogram obniżenia, głowice."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        cur = {**DEFAULT_W_OPTIONS, **self.config_entry.options}
        temp_filter = [
            {"domain": "sensor", "device_class": "temperature"},
            {"domain": "weather"},
        ]

        def sugg(key: str) -> dict:
            return {"suggested_value": cur.get(key)} if cur.get(key) else {}

        schema = vol.Schema(
            {
                vol.Optional(CONF_W_OUTDOOR, description=sugg(CONF_W_OUTDOOR)): selector.EntitySelector(
                    selector.EntitySelectorConfig(filter=temp_filter)
                ),
                vol.Optional(CONF_W_FALLBACK, description=sugg(CONF_W_FALLBACK)): selector.EntitySelector(
                    selector.EntitySelectorConfig(filter=temp_filter)
                ),
                vol.Optional(CONF_W_SETBACK, description=sugg(CONF_W_SETBACK)): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["schedule", "input_boolean", "binary_sensor", "switch"]
                    )
                ),
                vol.Optional(CONF_W_CLIMATES, description=sugg(CONF_W_CLIMATES)): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate", multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
