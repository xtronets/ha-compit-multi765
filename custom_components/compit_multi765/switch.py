"""Przełącznik „Sterowanie pogodowe”."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity

from .const import SWITCHES

from .entity import CompitEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entities: list[SwitchEntity] = [WeatherSwitch(entry)]
    entities += [CompitParamSwitch(entry, code, spec) for code, spec in SWITCHES.items()]
    async_add_entities(entities)


class WeatherSwitch(CompitEntity, SwitchEntity, RestoreEntity):
    """Włącza zapisywanie zadanej wyliczonej z krzywej grzewczej."""

    _attr_icon = "mdi:weather-partly-snowy"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "__tkotzad", "weather_control")
        self._wc = entry.runtime_data.weather

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        # Po restarcie tylko odtwarzamy stan – bez natychmiastowego zapisu.
        self._wc.enabled = last is not None and last.state == "on" and self._wc.configured

    @property
    def is_on(self) -> bool:
        return self._wc.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._wc.async_set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._wc.async_set_enabled(False)
        self.async_write_ha_state()


class CompitParamSwitch(CompitEntity, SwitchEntity):
    """Parametr TAK/NIE sterownika – w sekcji konfiguracji urządzenia."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, code: str, spec: dict) -> None:
        super().__init__(entry, code, spec["key"])
        self._attr_icon = spec["icon"]

    @property
    def is_on(self) -> bool | None:
        v = self.coordinator.value(self._code)
        try:
            return int(v) == 1
        except (TypeError, ValueError):
            return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_write(self._code, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_write(self._code, 0)
