"""Profile mocy: gotowe zestawy nastaw PID (wentylator MAX/MIN + czasy cyklu).

* 4 profile (łagodnie / normalnie / mróz / duży mróz), wartości edytowalne w HA.
* Wybór ręczny (encja select) albo automatyczny wg średniej temperatury
  zewnętrznej z 6 h – z histerezą i minimalnym odstępem między zmianami.
* Zapis do sterownika w kolejności, która nie łamie reguł DTR
  (wentylator MAX > MIN, cykl MIN ≥ cykl MAX + 60 s).

Stan i wartości profili są trzymane w .storage (przetrwają restart).
"""

from __future__ import annotations

from collections import deque
from datetime import timedelta
import logging
import time
from typing import Any, Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    MIN_CYCLE_GAP_S,
    NUMBERS,
    P_AVG_WINDOW_S,
    P_FIELDS,
    P_HYSTERESIS,
    P_MIN_AVG_SPAN_S,
    P_MIN_SWITCH_GAP_S,
    P_PROFILES,
    P_THRESHOLDS,
    P_TICK_S,
)

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1
CODES = {f: c for c, s in NUMBERS.items() for f in P_FIELDS if s["key"] == f}


class PowerProfiles:
    """Profile mocy jednego sterownika."""

    def __init__(self, hass: HomeAssistant, coordinator: Any, entry_id: str) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry_id}.power")
        self.values: dict[str, dict[str, float]] = {p: dict(v["defaults"]) for p, v in P_PROFILES.items()}
        self.thresholds: dict[str, float] = {k: v["default"] for k, v in P_THRESHOLDS.items()}
        self.active: str | None = None
        self.auto = False
        self.last_change: str | None = None
        self.last_reason: str | None = None
        self._last_auto_ts = 0.0
        self._samples: deque[tuple[float, float]] = deque()
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []

    # ------------------------------------------------------------ zapis/odczyt
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        for p, vals in (data.get("values") or {}).items():
            if p in self.values:
                self.values[p].update({k: float(v) for k, v in vals.items() if k in P_FIELDS})
        self.thresholds.update({k: float(v) for k, v in (data.get("thresholds") or {}).items() if k in self.thresholds})
        self.active = data.get("active") if data.get("active") in P_PROFILES else None
        self.auto = bool(data.get("auto"))
        self.last_change = data.get("last_change")
        self.last_reason = data.get("last_reason")
        if self.active is None:
            # Pierwsze uruchomienie: rozpoznaj profil po nastawach sterownika.
            self.active = self.matching_profile()

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(
            lambda: {
                "values": self.values,
                "thresholds": self.thresholds,
                "active": self.active,
                "auto": self.auto,
                "last_change": self.last_change,
                "last_reason": self.last_reason,
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

    @callback
    def async_start(self) -> None:
        self._unsubs.append(async_track_time_interval(self.hass, self._async_tick, timedelta(seconds=P_TICK_S)))
        self._unsubs.append(async_call_later(self.hass, 90, self._async_tick))

    @callback
    def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()

    # ---------------------------------------------------------------- odczyty
    def controller_values(self) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for f, code in CODES.items():
            v = self.coordinator.value(code)
            try:
                out[f] = float(v)
            except (TypeError, ValueError):
                out[f] = None
        return out

    def matching_profile(self) -> str | None:
        cur = self.controller_values()
        for p, vals in self.values.items():
            if all(cur[f] is not None and int(cur[f]) == int(vals[f]) for f in P_FIELDS):
                return p
        return None

    @property
    def matches_controller(self) -> bool | None:
        if self.active is None:
            return None
        cur = self.controller_values()
        if any(v is None for v in cur.values()):
            return None
        return all(int(cur[f]) == int(self.values[self.active][f]) for f in P_FIELDS)

    def _avg_temp(self) -> tuple[float | None, float]:
        if not self._samples:
            return None, 0.0
        span = self._samples[-1][0] - self._samples[0][0]
        return sum(v for _, v in self._samples) / len(self._samples), span

    def profile_for(self, t: float, current: str | None) -> str:
        """Profil dla temperatury t – z histerezą względem bieżącego profilu."""
        order = list(P_PROFILES)  # od najcieplejszego do najzimniejszego
        bounds = [self.thresholds[k] for k in P_THRESHOLDS]  # malejąco
        raw = sum(1 for b in bounds if t < b)
        if current not in order:
            return order[raw]
        idx = order.index(current)
        h = P_HYSTERESIS / 2
        # Zimniej: trzeba zejść poniżej granicy o h; cieplej: przekroczyć o h.
        while idx < len(order) - 1 and t < bounds[idx] - h:
            idx += 1
        while idx > 0 and t > bounds[idx - 1] + h:
            idx -= 1
        return order[idx]

    def attributes(self) -> dict[str, Any]:
        avg, span = self._avg_temp()
        suggested = None if avg is None else self.profile_for(avg, self.active)
        return {
            "auto": self.auto,
            "outdoor_avg_6h": None if avg is None else round(avg, 1),
            "outdoor_avg_span_h": round(span / 3600, 1),
            "suggested_profile": suggested,
            "matches_controller": self.matches_controller,
            "controller": self.controller_values(),
            "profile_values": self.values.get(self.active) if self.active else None,
            "thresholds": self.thresholds,
            "last_change": self.last_change,
            "last_reason": self.last_reason,
        }

    # ---------------------------------------------------------------- zmiany
    def _check_profile(self, vals: dict[str, float]) -> None:
        if vals["fan1_pmax"] <= vals["fan1_pmin"]:
            raise HomeAssistantError("Profil: wentylator MAX musi być wyższy niż MIN (DTR)")
        if vals["cycle_pmin"] < vals["cycle_pmax"] + MIN_CYCLE_GAP_S:
            raise HomeAssistantError(
                f"Profil: czas cyklu MIN musi być dłuższy od MAX o min. {MIN_CYCLE_GAP_S} s (DTR)"
            )

    async def _write_profile(self, profile: str) -> None:
        vals = self.values[profile]
        self._check_profile(vals)
        cur = self.controller_values()
        if any(v is None for v in cur.values()):
            raise HomeAssistantError("Brak aktualnych nastaw sterownika – zmiana profilu wstrzymana")
        # Wentylator: przy podnoszeniu najpierw MAX, przy obniżaniu najpierw MIN.
        fans = ["fan1_pmax", "fan1_pmin"] if vals["fan1_pmax"] >= cur["fan1_pmax"] else ["fan1_pmin", "fan1_pmax"]
        # Cykle: przy wydłużaniu najpierw MIN, przy skracaniu najpierw MAX.
        cycles = ["cycle_pmin", "cycle_pmax"] if vals["cycle_pmin"] >= cur["cycle_pmin"] else ["cycle_pmax", "cycle_pmin"]
        for f in fans + cycles:
            await self.coordinator.async_write(CODES[f], vals[f])

    async def async_select(self, profile: str, reason: str = "ręcznie") -> None:
        if profile not in P_PROFILES:
            raise HomeAssistantError(f"Nieznany profil {profile}")
        await self._write_profile(profile)
        if profile != self.active:
            _LOGGER.info("Profil mocy: %s → %s (%s)", self.active, profile, reason)
            self.last_change = dt_util.now().isoformat(timespec="seconds")
        self.active = profile
        self.last_reason = reason
        self._save()
        self._notify()

    async def async_select_manual(self, profile: str) -> None:
        """Wybór z encji select – wyłącza tryb automatyczny."""
        if self.auto:
            self.auto = False
            _LOGGER.info("Profil mocy: ręczny wybór – wyłączam tryb automatyczny")
        await self.async_select(profile, "ręcznie")

    async def async_set_auto(self, enabled: bool) -> None:
        if enabled and not self.coordinator.weather.configured:
            raise HomeAssistantError(
                "Automatyczny profil wymaga czujnika temperatury zewnętrznej (opcje integracji)."
            )
        self.auto = enabled
        if enabled:
            self._last_auto_ts = 0.0
        self._save()
        self._notify()
        if enabled:
            await self._async_tick()

    async def async_set_value(self, profile: str, field: str, value: float) -> None:
        new = {**self.values[profile], field: float(value)}
        self._check_profile(new)
        self.values[profile] = new
        self._save()
        if profile == self.active:
            await self.async_select(profile, "zmiana wartości profilu")
        else:
            self._notify()

    async def async_set_threshold(self, key: str, value: float) -> None:
        new = {**self.thresholds, key: float(value)}
        b = [new[k] for k in P_THRESHOLDS]
        if any(b[i] <= b[i + 1] for i in range(len(b) - 1)):
            raise HomeAssistantError("Progi profili muszą maleć: łagodnie/normalnie > normalnie/mróz > mróz/duży mróz")
        self.thresholds = new
        self._save()
        self._notify()

    # ------------------------------------------------------------------ auto
    async def _async_tick(self, _now: Any = None) -> None:
        t, _ = self.coordinator.weather._read_temp()  # noqa: SLF001
        now = time.monotonic()
        if t is not None:
            self._samples.append((now, t))
        while self._samples and now - self._samples[0][0] > P_AVG_WINDOW_S:
            self._samples.popleft()
        if self.auto:
            avg, span = self._avg_temp()
            if avg is not None and (span >= P_MIN_AVG_SPAN_S or self.active is None):
                target = self.profile_for(avg, self.active)
                gap_ok = now - self._last_auto_ts >= P_MIN_SWITCH_GAP_S or self._last_auto_ts == 0.0
                if target != self.active and gap_ok:
                    try:
                        await self.async_select(target, f"auto: średnia 6 h {avg:.1f} °C")
                    except HomeAssistantError as err:
                        _LOGGER.warning("Profil mocy: automatyczna zmiana na %s nieudana: %s", target, err)
                    else:
                        self._last_auto_ts = now
        self._notify()
