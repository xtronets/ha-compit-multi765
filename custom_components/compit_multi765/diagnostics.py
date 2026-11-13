"""Diagnostyka (Ustawienia → Urządzenia → Pobierz diagnostykę) – bez danych logowania."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

TO_REDACT = {CONF_EMAIL, CONF_PASSWORD, "token", "key", "gate_code", "code_gate"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data or {}
    weather = getattr(coordinator, "weather", None)
    power = getattr(coordinator, "power", None)
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "full_mode": data.get("full_mode"),
        "last_full_update_at": data.get("last_full_update_at"),
        "params": {
            p.get("code"): {
                "value": p.get("value"),
                "label": p.get("value_label"),
                "min": p.get("min"),
                "max": p.get("max"),
                "write": p.get("write"),
            }
            for p in data.get("params", [])
            if p
        },
        "weather_control": None if weather is None else weather.state,
        "power_profile": None if power is None else {"active": power.active, **power.attributes()},
    }
