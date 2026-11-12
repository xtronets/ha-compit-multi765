"""Przycisk „Odśwież ze sterownika” – odpowiednik „Pobierz grupę” w panelu iNext."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import CompitEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if entry.runtime_data.full is not None:
        async_add_entities([CompitReadButton(entry)])


class CompitReadButton(CompitEntity, ButtonEntity):
    _attr_icon = "mdi:database-refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "__tkotla", "controller_read")

    async def async_press(self) -> None:
        await self.coordinator.async_controller_read()
