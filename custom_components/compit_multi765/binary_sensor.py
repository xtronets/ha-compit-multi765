"""Stany pomp."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import CompitEntity

PUMPS = [("__pco", "pump_co"), ("__pcwu", "pump_cwu")]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(CompitPump(entry, code, key) for code, key in PUMPS)


class CompitPump(CompitEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool | None:
        v = self.coordinator.value(self._code)
        if v is None:
            return None
        try:
            return int(v) == 1
        except (TypeError, ValueError):
            return None
