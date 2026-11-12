"""Sterowanie pogodowe: zadana kotła z krzywej grzewczej (temp. zewnętrzna).

Logika:
  zadana = zadana_przy_0 - nachylenie * T_zew(średnia z 2 h)
           ograniczona do [min, max]
           - obniżenie (gdy encja harmonogramu obniżenia jest „on”)
           ± korekta od głowic (brak / duży odbiór ciepła w domu)
           ograniczona do [min, max] – min to twarda dolna granica

Zapis do sterownika tylko gdy różnica ≥ 2 °C i minęło ≥ 30 min od
poprzedniego zapisu. Zmiana stanu harmonogramu obniżenia lub włączenie
sterowania zapisuje od razu (bez czekania 30 min).
"""

from __future__ import annotations

from collections import deque
from datetime import timedelta
import logging
import math
import time
from typing import Any, Callable

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_W_CLIMATES,
    CONF_W_FALLBACK,
    CONF_W_OUTDOOR,
    CONF_W_SETBACK,
    DEFAULT_W_OPTIONS,
    W_AVG_WINDOW_S,
    W_DEMAND_HIGH_FOR_S,
    W_DEMAND_HIGH_SHARE,
    W_DEMAND_LOW_FOR_S,
    W_DEMAND_LOW_MAX,
    W_HARD_MIN,
    W_MIN_DELTA,
    W_MIN_WRITE_GAP_S,
    W_SETTINGS,
    W_TICK_S,
)

_LOGGER = logging.getLogger(__name__)
SETPOINT_CODE = "__tkotzad"


class WeatherControl:
    """Wylicza zadaną z krzywej i (gdy włączone) zapisuje ją do sterownika."""

    def __init__(self, hass: HomeAssistant, coordinator: Any, options: dict[str, Any]) -> None:
        self.hass = hass
        self.coordinator = coordinator
        opts = {**DEFAULT_W_OPTIONS, **(options or {})}
        self.outdoor: str | None = opts.get(CONF_W_OUTDOOR) or None
        self.fallback: str | None = opts.get(CONF_W_FALLBACK) or None
        self.setback_entity: str | None = opts.get(CONF_W_SETBACK) or None
        self.climates: list[str] = list(opts.get(CONF_W_CLIMATES) or [])

        self.enabled = False
        self.settings: dict[str, float] = {k: v["default"] for k, v in W_SETTINGS.items()}
        self.state: dict[str, Any] = {}
        self._samples: deque[tuple[float, float]] = deque()
        self._last_write_ts = 0.0
        self._last_write_at: str | None = None
        self._last_setback: bool | None = None
        self._low_since: float | None = None
        self._high_since: float | None = None
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []

    # ---------------------------------------------------------------- cykl życia
    @callback
    def async_start(self) -> None:
        self._unsubs.append(
            async_track_time_interval(self.hass, self._async_tick, timedelta(seconds=W_TICK_S))
        )
        if self.setback_entity:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.setback_entity], self._async_setback_changed
                )
            )
        # Pierwsze przeliczenie po chwili – encje zdążą odtworzyć stan.
        self._unsubs.append(async_call_later(self.hass, 60, self._async_tick))

    @callback
    def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()

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

    # ------------------------------------------------------------- ustawienia
    async def async_set_enabled(self, enabled: bool) -> None:
        if enabled and not self.configured:
            raise HomeAssistantError(
                "Najpierw wybierz czujnik temperatury zewnętrznej w opcjach integracji "
                "(Ustawienia → Urządzenia i usługi → Compit MULTI 765 → Konfiguruj)."
            )
        self.enabled = enabled
        if enabled:
            self._last_write_ts = 0.0  # pozwól zapisać od razu
        await self.async_evaluate(force=enabled)

    async def async_set_setting(self, key: str, value: float, evaluate: bool = True) -> None:
        self.settings[key] = float(value)
        if evaluate:
            await self.async_evaluate()

    # ------------------------------------------------------------------ odczyty
    @property
    def configured(self) -> bool:
        """Czy wskazano jakiekolwiek źródło temperatury zewnętrznej."""
        return bool(self.outdoor or self.fallback)

    def _read_temp(self) -> tuple[float | None, str | None]:
        """Temperatura zewnętrzna w °C z czujnika (sensor) lub encji pogody (weather)."""
        for ent in (self.outdoor, self.fallback):
            if not ent:
                continue
            st = self.hass.states.get(ent)
            if st is None:
                continue
            if st.domain == "weather":
                raw = st.attributes.get("temperature")
                unit = st.attributes.get("temperature_unit")
            else:
                raw = st.state
                unit = st.attributes.get("unit_of_measurement")
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if unit in ("°F", "F"):
                value = (value - 32) * 5 / 9
            return value, ent
        return None, None

    def _sample(self) -> None:
        t, _ = self._read_temp()
        now = time.monotonic()
        if t is not None:
            self._samples.append((now, t))
        while self._samples and now - self._samples[0][0] > W_AVG_WINDOW_S:
            self._samples.popleft()

    def _avg_temp(self) -> float | None:
        if not self._samples:
            return None
        return sum(v for _, v in self._samples) / len(self._samples)

    def _setback_active(self) -> bool:
        if not self.setback_entity:
            return False
        st = self.hass.states.get(self.setback_entity)
        return st is not None and st.state == "on"

    def _demand(self) -> tuple[int, int, float]:
        """Zwraca (ile głowic grzeje, ile głowic, korekta °C)."""
        n = 0
        heating = 0
        for ent in self.climates:
            st = self.hass.states.get(ent)
            if st is None or st.state in ("unavailable", "unknown", "off"):
                continue
            n += 1
            if st.attributes.get("hvac_action") == "heating":
                heating += 1
        corr = 0.0
        step = self.settings.get("demand", 0.0)
        now = time.monotonic()
        if n == 0 or step <= 0:
            self._low_since = self._high_since = None
            return heating, n, 0.0
        if heating <= W_DEMAND_LOW_MAX:
            self._low_since = self._low_since or now
            self._high_since = None
            if now - self._low_since >= W_DEMAND_LOW_FOR_S:
                corr = -step
        elif heating >= math.ceil(n * W_DEMAND_HIGH_SHARE):
            self._high_since = self._high_since or now
            self._low_since = None
            if now - self._high_since >= W_DEMAND_HIGH_FOR_S:
                corr = step
        else:
            self._low_since = self._high_since = None
        return heating, n, corr

    # ---------------------------------------------------------------- logika
    async def _async_tick(self, _now: Any = None) -> None:
        self._sample()
        await self.async_evaluate()

    async def _async_setback_changed(self, _event: Event) -> None:
        await self.async_evaluate()

    def compute(self) -> dict[str, Any]:
        s = self.settings
        t_now, src = self._read_temp()
        t_avg = self._avg_temp()
        if t_avg is None:
            t_avg = t_now
        heating, n, corr = self._demand()
        setback = self._setback_active()
        result: dict[str, Any] = {
            "outdoor_now": t_now,
            "outdoor_avg_2h": None if t_avg is None else round(t_avg, 1),
            "outdoor_source": src,
            "setback_active": setback,
            "setback": s["setback"] if setback else 0,
            "heads_heating": heating,
            "heads_total": n,
            "demand_correction": corr,
        }
        if t_avg is None:
            result["target"] = None
            result["reason"] = (
                "brak odczytu temperatury zewnętrznej"
                if self.configured
                else "nie wybrano czujnika temperatury zewnętrznej (opcje integracji)"
            )
            return result
        curve = s["at0"] - s["slope"] * t_avg
        curve = min(max(curve, s["tmin"]), s["tmax"])
        target = curve - result["setback"] + corr
        # „Krzywa: minimum” to twarda dolna granica całej zadanej (także po obniżeniu i korekcie).
        target = min(max(target, s["tmin"], W_HARD_MIN), s["tmax"])
        result["curve"] = round(curve, 1)
        result["target"] = int(round(target))
        return result

    async def async_evaluate(self, force: bool = False) -> None:
        res = self.compute()
        current = self.coordinator.value(SETPOINT_CODE)
        try:
            current = None if current is None else float(current)
        except (TypeError, ValueError):
            current = None
        target = res.get("target")
        setback_changed = self._last_setback is not None and self._last_setback != res["setback_active"]
        gap_ok = time.monotonic() - self._last_write_ts >= W_MIN_WRITE_GAP_S
        action = "obserwacja (wyłączone)"

        if self.enabled and target is not None and current is not None:
            diff = target - current
            urgent = force or setback_changed
            if diff == 0:
                action = "bez zmian"
                self._last_setback = res["setback_active"]
            elif urgent or (abs(diff) >= W_MIN_DELTA and gap_ok):
                try:
                    await self.coordinator.async_write(SETPOINT_CODE, target)
                except HomeAssistantError as err:
                    action = f"błąd zapisu: {err}"
                    _LOGGER.warning("Sterowanie pogodowe: nie zapisano zadanej %s: %s", target, err)
                else:
                    self._last_write_ts = time.monotonic()
                    self._last_write_at = dt_util.now().isoformat(timespec="seconds")
                    self._last_setback = res["setback_active"]
                    action = f"zapisano {int(current)} → {target}"
                    _LOGGER.info("Sterowanie pogodowe: zadana %s → %s (%s)", current, target, res)
            elif abs(diff) < W_MIN_DELTA:
                action = f"różnica {diff:+.0f} °C < {W_MIN_DELTA} – bez zapisu"
            else:
                action = "czekam na odstęp 30 min"
        elif self._last_setback is None:
            self._last_setback = res["setback_active"]

        res.update(
            {
                "enabled": self.enabled,
                "controller_setpoint": current,
                "last_action": action,
                "last_write": self._last_write_at,
                "settings": dict(self.settings),
            }
        )
        self.state = res
        self._notify()
