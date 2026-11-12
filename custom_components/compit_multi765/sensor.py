"""Sensory: temperatury, paliwo oraz diagnostyczna lista wszystkich parametrów."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import CompitEntity

MEASUREMENTS = [
    # kod, klucz tłumaczenia, jednostka, device_class
    ("__tkotla", "boiler_temp", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    ("__tpowrotu", "return_temp", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    ("__poziompaliwa", "fuel_level", PERCENTAGE, None),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entities: list[SensorEntity] = [
        CompitMeasurement(entry, code, key, unit, dc) for code, key, unit, dc in MEASUREMENTS
    ]
    entities.append(CompitParamsSensor(entry))
    entities.append(WeatherTargetSensor(entry))
    async_add_entities(entities)


class WeatherTargetSensor(CompitEntity, SensorEntity):
    """Zadana wyliczona z krzywej grzewczej (także gdy sterowanie wyłączone)."""

    _attr_icon = "mdi:home-thermometer-outline"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = frozenset({"settings", "last_action"})

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "__tkotzad", "weather_target")
        self._wc = entry.runtime_data.weather

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._wc.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> int | None:
        return self._wc.state.get("target")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {k: v for k, v in self._wc.state.items() if k != "target"}


class CompitMeasurement(CompitEntity, SensorEntity):
    """Pomiar odczytany ze sterownika."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry, code, key, unit, device_class) -> None:
        super().__init__(entry, code, key)
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        if code == "__poziompaliwa":
            self._attr_icon = "mdi:gauge"

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.value(self._code)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None


class CompitParamsSensor(CompitEntity, SensorEntity):
    """Liczba parametrów; atrybuty: kod → wartość / zakres / zapis."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:format-list-numbered"
    # Atrybuty bywają duże – nie zapisujemy ich do bazy recordera.
    _unrecorded_attributes = frozenset({"params"})

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "__tkotla", "parameters")

    @property
    def _params(self) -> list[dict[str, Any]]:
        data = self.coordinator.data or {}
        return [p for p in data.get("params", []) if p]

    @property
    def native_value(self) -> int:
        return len(self._params)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {
            "last_connected_at": data.get("last_connected_at"),
            "last_full_update_at": data.get("last_full_update_at"),
            "full_mode": data.get("full_mode"),
            "errors": data.get("errors"),
            "writable_count": sum(1 for p in self._params if p.get("write")),
            "params": {
                p["code"]: {
                    "value": p.get("value"),
                    "label": p.get("value_label"),
                    "min": p.get("min"),
                    "max": p.get("max"),
                    "write": p.get("write"),
                    "hidden": p.get("hidden"),
                }
                for p in self._params
            },
        }
