"""Wybór profilu mocy (zestaw nastaw PID)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import P_PROFILES
from .entity import CompitEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([PowerProfileSelect(entry)])


class PowerProfileSelect(CompitEntity, SelectEntity):
    """Profil mocy – ręczny wybór wyłącza tryb automatyczny."""

    _attr_icon = "mdi:fire-circle"
    _attr_options = list(P_PROFILES)
    _unrecorded_attributes = frozenset({"controller", "profile_values", "thresholds"})

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "__pidczascyklu", "power_profile")
        self._pp = entry.runtime_data.power

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._pp.add_listener(self.async_write_ha_state))

    @property
    def current_option(self) -> str | None:
        return self._pp.active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._pp.attributes()

    async def async_select_option(self, option: str) -> None:
        await self._pp.async_select_manual(option)
