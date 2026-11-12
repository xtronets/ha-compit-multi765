"""Stałe integracji Compit MULTI 765."""

DOMAIN = "compit_multi765"

API_URL = "https://inext.compit.pl/mobile/v2/compit"
CLIENT_UID = "HomeAssistant-MULTI765"
CLIENT_LABEL = "Home Assistant MULTI765"

CONF_DEVICE_ID = "device_id"
CONF_DEVICE_LABEL = "device_label"

SCAN_INTERVAL_SECONDS = 120
DUMP_FILENAME = "compit_multi765_dump.json"

# Etap 1: zapis tylko parametrów z listy NUMBERS, w zawężonych zakresach.
# Zakresy są celowo węższe niż dopuszcza sterownik (bezpieczeństwo kotła węglowego).
NUMBERS: dict[str, dict] = {
    "__tkotzad": {"key": "boiler_setpoint", "min": 55, "max": 80, "step": 1, "unit": "°C", "icon": "mdi:thermometer-water"},
    "__pidwentylatorpmax": {"key": "fan1_pmax", "min": 15, "max": 60, "step": 1, "unit": "%", "icon": "mdi:fan"},
    "__pidwentylatorpmin": {"key": "fan1_pmin", "min": 15, "max": 60, "step": 1, "unit": "%", "icon": "mdi:fan-chevron-down"},
    "__pidczascyklu": {"key": "cycle_pmax", "min": 120, "max": 600, "step": 5, "unit": "s", "icon": "mdi:timer-outline"},
    "__pidczascyklumin": {"key": "cycle_pmin", "min": 120, "max": 600, "step": 5, "unit": "s", "icon": "mdi:timer-outline"},
    "__podtrzymaniewentylator": {"key": "hold_fan1", "min": 15, "max": 60, "step": 1, "unit": "%", "icon": "mdi:fan-off"},
    "__podtrzymanieczascyklu": {"key": "hold_cycle", "min": 15, "max": 90, "step": 1, "unit": "min", "icon": "mdi:timer-sand"},
    # v0.2 – parametry dostępne tylko w pełnym stanie (panel WWW)
    "__obrotywent2mocmax": {"key": "fan2_pmax", "min": 15, "max": 70, "step": 1, "unit": "%", "icon": "mdi:fan-plus"},
    "__pidobrotywent2mocmin": {"key": "fan2_pmin", "min": 15, "max": 70, "step": 1, "unit": "%", "icon": "mdi:fan-minus"},
    "__podtrzymanieobrwent2": {"key": "hold_fan2", "min": 15, "max": 70, "step": 1, "unit": "%", "icon": "mdi:fan-off"},
    "__tpowrotmin": {"key": "return_min", "min": 44, "max": 60, "step": 1, "unit": "°C", "icon": "mdi:thermometer-chevron-up"},
    "__histerezakotla": {"key": "boiler_hysteresis", "min": 1, "max": 5, "step": 1, "unit": "°C", "icon": "mdi:arrow-expand-vertical"},
    "__przejsciewpodtrzymanie": {"key": "hold_transition", "min": 1, "max": 10, "step": 1, "unit": "°C", "icon": "mdi:swap-vertical"},
    "__pojemnosczasobnika": {"key": "hopper_capacity", "min": 200, "max": 1000, "step": 1, "unit": "min", "icon": "mdi:silo"},
}

# Pełny stan (119 parametrów) to kopia w chmurze – odpytujemy rzadziej niż stan podstawowy.
FULL_STATE_INTERVAL_S = 600
# Po „Odśwież ze sterownika” bramka potrzebuje chwili na odczyt.
FULL_READ_WAIT_S = (30, 75)

# Reguły z DTR Carbo 1 sprawdzane przed każdym zapisem.
MIN_CYCLE_GAP_S = 60  # czas cyklu Pmin musi być dłuższy od Pmax o co najmniej 60 s

# Po zapisie chmura przekazuje wartość do sterownika z opóźnieniem – odświeżamy stan.
REFRESH_AFTER_WRITE_S = (30, 90)

# ---------------------------------------------------------------- v0.3 pogodówka
CONF_W_OUTDOOR = "weather_outdoor"
CONF_W_FALLBACK = "weather_fallback"
CONF_W_SETBACK = "weather_setback"
CONF_W_CLIMATES = "weather_climates"

DEFAULT_W_OPTIONS = {
    CONF_W_OUTDOOR: None,
    CONF_W_FALLBACK: None,
    CONF_W_SETBACK: None,
    CONF_W_CLIMATES: [],
}

# Nastawy krzywej (encje number lokalne, pamiętane po restarcie).
W_SETTINGS: dict[str, dict] = {
    "at0": {"key": "w_at0", "default": 62, "min": 50, "max": 75, "step": 1, "unit": "°C", "icon": "mdi:chart-line"},
    "slope": {"key": "w_slope", "default": 0.6, "min": 0, "max": 2, "step": 0.1, "unit": "°C/°C", "icon": "mdi:slope-downhill"},
    "tmin": {"key": "w_tmin", "default": 58, "min": 55, "max": 70, "step": 1, "unit": "°C", "icon": "mdi:thermometer-chevron-down"},
    "tmax": {"key": "w_tmax", "default": 72, "min": 60, "max": 80, "step": 1, "unit": "°C", "icon": "mdi:thermometer-chevron-up"},
    "setback": {"key": "w_setback", "default": 3, "min": 0, "max": 15, "step": 1, "unit": "°C", "icon": "mdi:arrow-down-bold"},
    "demand": {"key": "w_demand", "default": 2, "min": 0, "max": 5, "step": 0.5, "unit": "°C", "icon": "mdi:radiator"},
}

W_TICK_S = 300  # przeliczenie co 5 min
W_AVG_WINDOW_S = 2 * 3600  # średnia temp. zewnętrznej z 2 h
W_MIN_DELTA = 2  # zapis dopiero przy różnicy ≥ 2 °C
W_MIN_WRITE_GAP_S = 1800  # i nie częściej niż co 30 min
W_HARD_MIN = 55  # nigdy poniżej (ochrona powrotu)
W_DEMAND_LOW_MAX = 1  # „brak odbioru” = grzeje najwyżej 1 głowica…
W_DEMAND_LOW_FOR_S = 900  # …przez 15 min
W_DEMAND_HIGH_SHARE = 0.6  # „duży odbiór” = grzeje ≥ 60 % głowic…
W_DEMAND_HIGH_FOR_S = 1800  # …przez 30 min

# v0.3.2 – przełączniki parametrów TAK/NIE (sekcja konfiguracji urządzenia)
SWITCHES: dict[str, dict] = {
    "__pracazpodajmikiem": {"key": "feeder_mode", "min": 0, "max": 1, "icon": "mdi:screw-lag"},
}
