"""Śledzenie opału: kg w zasobniku, średnie spalanie, terminy dosypania i kalibracja.

Sterownik podaje tylko poziom paliwa w % (szacowany z czasu pracy podajnika).
Ten moduł:
  * wykrywa dosypanie (skok poziomu o ≥ 10 pkt %),
  * liczy średnie spalanie od ostatniego dosypania (stabilne, nie „pływa”),
  * przelicza % na kg wg pojemności zasobnika,
  * uczy się pojemności zasobnika, gdy użytkownik poda, ile kg dosypał.

Stan jest zapisywany w .storage, więc przetrwa restart Home Assistanta.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    FUEL_CODE,
    FUEL_DEFAULT_RATE_PCT_H,
    FUEL_MIN_HOURS,
    FUEL_PENDING_MAX_H,
    FUEL_REFILL_JUMP,
    FUEL_SETTINGS,
)

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1


class FuelTracker:
    """Stan opału jednego sterownika."""

    def __init__(self, hass: HomeAssistant, coordinator: Any, entry_id: str) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry_id}.fuel")
        self.settings: dict[str, float] = {k: v["default"] for k, v in FUEL_SETTINGS.items()}
        self.refill_time: datetime | None = None
        self.refill_level: float | None = None
        self.prev_rate: float | None = None
        self.last_fuel: float | None = None
        self.calibrations: int = 0
        self.pending_kg: float | None = None
        self.pending_at: datetime | None = None
        self.last_refill_jump: float | None = None
        self.last_calibration: dict[str, Any] | None = None
        self._listeners: list[Callable[[], None]] = []

    # ------------------------------------------------------------ zapis/odczyt
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.settings.update(data.get("settings", {}))
        self.refill_time = dt_util.parse_datetime(data["refill_time"]) if data.get("refill_time") else None
        self.refill_level = data.get("refill_level")
        self.prev_rate = data.get("prev_rate")
        self.last_fuel = data.get("last_fuel")
        self.calibrations = data.get("calibrations", 0)
        self.last_calibration = data.get("last_calibration")

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(
            lambda: {
                "settings": self.settings,
                "refill_time": self.refill_time.isoformat() if self.refill_time else None,
                "refill_level": self.refill_level,
                "prev_rate": self.prev_rate,
                "last_fuel": self.last_fuel,
                "calibrations": self.calibrations,
                "last_calibration": self.last_calibration,
            },
            5,
        )

    @callback
    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)

        def _remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _remove

    @callback
    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    # ------------------------------------------------------------- aktualizacja
    @property
    def fuel(self) -> float | None:
        v = self.coordinator.value(FUEL_CODE)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @callback
    def handle_update(self) -> None:
        """Wywoływane po każdym odświeżeniu koordynatora."""
        fuel = self.fuel
        if fuel is None:
            return
        now = dt_util.utcnow()
        if self.refill_time is None:
            # Pierwsze uruchomienie – zaczynamy liczyć od teraz.
            self.refill_time, self.refill_level = now, fuel
        elif self.last_fuel is not None and fuel - self.last_fuel >= FUEL_REFILL_JUMP:
            self._on_refill(now, self.last_fuel, fuel)
        self.last_fuel = fuel
        if self.pending_kg is not None and self.pending_at and now - self.pending_at > timedelta(hours=FUEL_PENDING_MAX_H):
            _LOGGER.info("Opał: nie wykryto dosypania w ciągu %s h – pomijam kalibrację", FUEL_PENDING_MAX_H)
            self.pending_kg = self.pending_at = None
        self._save()
        self._notify()

    def _on_refill(self, now: datetime, before: float, after: float) -> None:
        hrs = self.hours_since_refill()
        if hrs and hrs >= FUEL_MIN_HOURS and self.refill_level is not None and self.refill_level > before:
            # Średnie spalanie zakończonego cyklu – posłuży, dopóki nowy cykl nie ma 6 h.
            self.prev_rate = (self.refill_level - before) / hrs
        self.refill_time, self.refill_level = now, after
        self.last_refill_jump = after - before
        _LOGGER.info("Opał: wykryto dosypanie %.0f%% → %.0f%%", before, after)
        if self.pending_kg is not None:
            self._calibrate(self.pending_kg, self.last_refill_jump)
            self.pending_kg = self.pending_at = None

    # ---------------------------------------------------------------- kalibracja
    async def async_record_refill(self, kg: float) -> None:
        """Użytkownik podał, ile kg dosypał. Kalibracja przy najbliższym (lub niedawnym) skoku %."""
        if kg <= 0:
            return
        now = dt_util.utcnow()
        recent = (
            self.last_refill_jump is not None
            and self.refill_time is not None
            and now - self.refill_time <= timedelta(hours=FUEL_PENDING_MAX_H)
        )
        if recent:
            self._calibrate(kg, self.last_refill_jump)
            self.last_refill_jump = None
        else:
            self.pending_kg, self.pending_at = kg, now
        self._save()
        self._notify()

    def _calibrate(self, kg: float, jump_pct: float) -> None:
        if jump_pct < FUEL_REFILL_JUMP:
            return
        measured = kg / jump_pct * 100
        spec = FUEL_SETTINGS["hopper_kg"]
        measured = min(max(measured, spec["min"]), spec["max"])
        old = self.settings["hopper_kg"]
        new = measured if self.calibrations == 0 else 0.5 * old + 0.5 * measured
        self.settings["hopper_kg"] = round(new, 1)
        self.calibrations += 1
        self.last_calibration = {
            "at": dt_util.utcnow().isoformat(),
            "kg": kg,
            "jump_pct": round(jump_pct, 1),
            "measured_hopper_kg": round(measured, 1),
            "hopper_kg_before": old,
            "hopper_kg_after": self.settings["hopper_kg"],
        }
        _LOGGER.info("Opał: kalibracja %s kg / %.0f%% → zasobnik %.1f kg", kg, jump_pct, new)

    async def async_set_setting(self, key: str, value: float) -> None:
        self.settings[key] = float(value)
        self._save()
        self._notify()

    # ------------------------------------------------------------------ wyniki
    def hours_since_refill(self) -> float | None:
        if self.refill_time is None:
            return None
        return (dt_util.utcnow() - self.refill_time).total_seconds() / 3600

    def rate_pct_h(self, allow_default: bool = True) -> float | None:
        fuel, hrs = self.fuel, self.hours_since_refill()
        if fuel is not None and hrs is not None and self.refill_level is not None and hrs >= FUEL_MIN_HOURS:
            used = self.refill_level - fuel
            if used > 0:
                return used / hrs
        if self.prev_rate:
            return self.prev_rate
        return FUEL_DEFAULT_RATE_PCT_H if allow_default else None

    @property
    def rate_source(self) -> str:
        hrs = self.hours_since_refill()
        if hrs is not None and hrs >= FUEL_MIN_HOURS and self.fuel is not None and (self.refill_level or 0) > self.fuel:
            return "od dosypania"
        return "poprzedni cykl" if self.prev_rate else "domyślne"

    @property
    def kg_per_pct(self) -> float:
        return self.settings["hopper_kg"] / 100

    def fuel_kg(self) -> float | None:
        return None if self.fuel is None else round(self.fuel * self.kg_per_pct, 1)

    def burn_kg_h(self) -> float | None:
        r = self.rate_pct_h()
        return None if r is None else round(r * self.kg_per_pct, 2)

    def time_at_level(self, level: float) -> datetime | None:
        fuel, r = self.fuel, self.rate_pct_h()
        if fuel is None or not r:
            return None
        return dt_util.utcnow() + timedelta(hours=max(fuel - level, 0) / r)

    def attributes(self) -> dict[str, Any]:
        r = self.rate_pct_h()
        return {
            "rate_pct_h": None if r is None else round(r, 2),
            "kg_per_day": None if r is None else round(r * self.kg_per_pct * 24, 1),
            "rate_source": self.rate_source,
            "refill_time": self.refill_time.isoformat() if self.refill_time else None,
            "refill_level": self.refill_level,
            "hours_since_refill": None if self.hours_since_refill() is None else round(self.hours_since_refill(), 1),
            "hopper_kg": self.settings["hopper_kg"],
            "calibrations": self.calibrations,
            "pending_refill_kg": self.pending_kg,
            "last_calibration": self.last_calibration,
        }
