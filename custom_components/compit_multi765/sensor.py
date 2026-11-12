"""Sensory: temperatury, paliwo oraz diagnostyczna lista wszystkich parametrów."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfMass, UnitOfTemperature
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
    entities += [
        FuelSensor(entry, "fuel_kg"),
        FuelSensor(entry, "fuel_burn"),
        FuelSensor(entry, "fuel_refill_at"),
        FuelSensor(entry, "fuel_empty_at"),
    ]
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


class FuelSensor(CompitEntity, SensorEntity):
    """Opał liczony w HA: kg, spalanie, terminy."""

    def __init__(self, entry: ConfigEntry, key: str) -> None:
        super().__init__(entry, "__poziompaliwa", key)
        self._key = key
        self._fuel = entry.runtime_data.fuel
        if key == "fuel_kg":
            self._attr_device_class = SensorDeviceClass.WEIGHT
            self._attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_icon = "mdi:sack"
        elif key == "fuel_burn":
            self._attr_native_unit_of_measurement = "kg/h"
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_icon = "mdi:fire"
            self._attr_suggested_display_precision = 2
        else:
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
            self._attr_icon = "mdi:calendar-clock" if key == "fuel_refill_at" else "mdi:calendar-alert"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._fuel.add_listener(self.async_write_ha_state))

    @property
    def native_value(self):
        f = self._fuel
        if self._key == "fuel_kg":
            return f.fuel_kg()
        if self._key == "fuel_burn":
            return f.burn_kg_h()
        if self._key == "fuel_refill_at":
            return f.time_at_level(f.settings["refill_pct"])
        return f.time_at_level(0)

    @property
    def extra_state_attributes(self):
        if self._key == "fuel_burn":
            return self._fuel.attributes()
        if self._key == "fuel_kg":
            return {"hopper_kg": self._fuel.settings["hopper_kg"], "calibrations": self._fuel.calibrations}
        return None
