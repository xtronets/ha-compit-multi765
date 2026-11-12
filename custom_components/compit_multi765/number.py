"""Nastawy sterownika z bezpiecznym zapisem (zakresy + reguły DTR)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import FUEL_SETTINGS, NUMBERS, W_SETTINGS
from .entity import CompitEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entities: list[NumberEntity] = [CompitNumber(entry, code, spec) for code, spec in NUMBERS.items()]
    entities += [WeatherSettingNumber(entry, name, spec) for name, spec in W_SETTINGS.items()]
    entities += [FuelSettingNumber(entry, name, spec) for name, spec in FUEL_SETTINGS.items()]
    entities.append(FuelRefillNumber(entry))
    async_add_entities(entities)


class CompitNumber(CompitEntity, NumberEntity):
    """Jedna nastawa sterownika."""

    _attr_mode = NumberMode.BOX

    def __init__(self, entry: ConfigEntry, code: str, spec: dict) -> None:
        super().__init__(entry, code, spec["key"])
        self._attr_native_min_value = spec["min"]
        self._attr_native_max_value = spec["max"]
        self._attr_native_step = spec["step"]
        self._attr_native_unit_of_measurement = spec["unit"]
        self._attr_icon = spec["icon"]
        if code != "__tkotzad":
            # Nastawy palnika – w sekcji konfiguracji urządzenia, nie na głównej karcie.
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self) -> float | None:
        v = self.coordinator.value(self._code)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write(self._code, value)


class WeatherSettingNumber(CompitEntity, RestoreNumber):
    """Nastawa krzywej grzewczej – trzymana w HA, nie w sterowniku."""

    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, name: str, spec: dict) -> None:
        super().__init__(entry, "__tkotzad", spec["key"])
        self._name = name
        self._wc = entry.runtime_data.weather
        self._attr_native_min_value = spec["min"]
        self._attr_native_max_value = spec["max"]
        self._attr_native_step = spec["step"]
        self._attr_native_unit_of_measurement = spec["unit"]
        self._attr_icon = spec["icon"]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            await self._wc.async_set_setting(self._name, last.native_value, evaluate=False)

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> float:
        return self._wc.settings[self._name]

    async def async_set_native_value(self, value: float) -> None:
        await self._wc.async_set_setting(self._name, value)
        self.async_write_ha_state()


class FuelSettingNumber(CompitEntity, NumberEntity):
    """Pojemność zasobnika (kg) i próg dosypania (%) – zapisywane w HA."""

    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, name: str, spec: dict) -> None:
        super().__init__(entry, "__poziompaliwa", spec["key"])
        self._name = name
        self._fuel = entry.runtime_data.fuel
        self._attr_native_min_value = spec["min"]
        self._attr_native_max_value = spec["max"]
        self._attr_native_step = spec["step"]
        self._attr_native_unit_of_measurement = spec["unit"]
        self._attr_icon = spec["icon"]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._fuel.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> float:
        return self._fuel.settings[self._name]

    async def async_set_native_value(self, value: float) -> None:
        await self._fuel.async_set_setting(self._name, value)


class FuelRefillNumber(CompitEntity, NumberEntity):
    """„Dosypano węgla (kg)” – wpisanie wartości kalibruje pojemność zasobnika."""

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 1000
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "kg"
    _attr_icon = "mdi:basket-fill"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "__poziompaliwa", "fuel_refill_kg")
        self._fuel = entry.runtime_data.fuel
        self._last: float = 0

    @property
    def native_value(self) -> float:
        return self._fuel.pending_kg or self._last

    async def async_set_native_value(self, value: float) -> None:
        self._last = value
        await self._fuel.async_record_refill(value)
        self.async_write_ha_state()
