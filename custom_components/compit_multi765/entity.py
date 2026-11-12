"""Wspólna klasa bazowa encji sterownika."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_LABEL, DOMAIN


class CompitEntity(CoordinatorEntity):
    """Encja powiązana z jednym urządzeniem MULTI 765."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, code: str, key: str) -> None:
        super().__init__(entry.runtime_data)
        self._code = code
        device_id = entry.runtime_data.device_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device_id))},
            name=entry.title,
            manufacturer="Compit",
            model=entry.data.get(CONF_DEVICE_LABEL, "MULTI 765"),
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.param(self._code) is not None
