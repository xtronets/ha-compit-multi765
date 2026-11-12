/*
 * Compit Boiler Card – karta kotła dla integracji Compit MULTI 765 (iNext).
 * Rejestrowana automatycznie przez integrację; w edytorze dashboardu: „Kocioł Compit”.
 *
 * Konfiguracja (wszystko opcjonalne):
 *   type: custom:compit-boiler-card
 *   device: <device_id>      # domyślnie pierwszy sterownik Compit
 *   title: Kocioł węglowy    # domyślnie nazwa urządzenia
 *   subtitle: Carbo 1 · 25 kW
 */

const DOMAIN = "compit_multi765";
const VERSION = "1.2.0";

const KEYS = {
  boiler: "boiler_temp",
  ret: "return_temp",
  fuelPct: "fuel_level",
  pump: "pump_co",
  setpoint: "boiler_setpoint",
  weather: "weather_control",
  weatherTarget: "weather_target",
  at0: "w_at0",
  feeder: "feeder_mode",
  fuelKg: "fuel_kg",
  burn: "fuel_burn",
  refillAt: "fuel_refill_at",
  emptyAt: "fuel_empty_at",
};

const T = {
  pl: {
    boiler: "KOCIOŁ", setpoint: "ZADANA", auto: "AUTO", weather: "POGODA", feeder: "PODAJNIK",
    on: "WŁ.", off: "WYŁ.", pump: "POMPA CO", running: "pracuje", stopped: "stoi",
    fuel: "OPAŁ", burn: "spalanie", perDay: "kg/doba", refill: "dosyp", empty: "pusty",
    ret: "POWRÓT", outdoor: "zew.", curve: "krzywa", heating: "GRZEJE", hot: "ROZPALONY",
    cold: "WYGASZONY", ash: "POPIELNIK", noDevice: "Nie znaleziono sterownika Compit MULTI 765.",
    feederConfirmOff: "Wyłączyć podajnik? Węgiel przestanie być podawany – kocioł po chwili wygaśnie.",
    feederConfirmOn: "Włączyć z powrotem podawanie węgla?",
  },
  en: {
    boiler: "BOILER", setpoint: "SETPOINT", auto: "AUTO", weather: "WEATHER", feeder: "FEEDER",
    on: "ON", off: "OFF", pump: "CH PUMP", running: "running", stopped: "stopped",
    fuel: "FUEL", burn: "burn rate", perDay: "kg/day", refill: "refill", empty: "empty",
    ret: "RETURN", outdoor: "out", curve: "curve", heating: "HEATING", hot: "HOT",
    cold: "OFF", ash: "ASH PAN", noDevice: "No Compit MULTI 765 controller found.",
    feederConfirmOff: "Turn the feeder off? Fuel will stop and the boiler will go out.",
    feederConfirmOn: "Turn the fuel feeder back on?",
  },
};

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const num = (s) => {
  const v = parseFloat(s?.state);
  return Number.isFinite(v) ? v : null;
};
const clamp = (v, a, b) => Math.min(Math.max(v, a), b);

class CompitBoilerCard extends HTMLElement {
  static getConfigForm() {
    return {
      schema: [
        { name: "device", selector: { device: { integration: DOMAIN } } },
        { name: "title", selector: { text: {} } },
        { name: "subtitle", selector: { text: {} } },
      ],
      computeLabel: (s) => ({ device: "Sterownik / Controller", title: "Tytuł / Title", subtitle: "Podtytuł / Subtitle" })[s.name],
    };
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    this._config = { ...config };
    this._key = null;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 9;
  }

  getGridOptions() {
    return { columns: 12, rows: "auto", min_columns: 6 };
  }

  // ------------------------------------------------------------ encje urządzenia
  _deviceId() {
    if (this._config.device) return this._config.device;
    const ent = Object.values(this._hass.entities || {}).find((e) => e.platform === DOMAIN && e.device_id);
    return ent?.device_id;
  }

  _entities(deviceId) {
    const map = {};
    for (const e of Object.values(this._hass.entities || {})) {
      if (e.platform !== DOMAIN || e.device_id !== deviceId || !e.translation_key) continue;
      for (const [k, tk] of Object.entries(KEYS)) if (e.translation_key === tk) map[k] = e.entity_id;
    }
    return map;
  }

  // ---------------------------------------------------------------- akcje
  _moreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }));
  }

  _toast(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }));
  }

  async _call(domain, service, data) {
    try {
      await this._hass.callService(domain, service, data);
    } catch (err) {
      this._toast(err?.message || String(err));
    }
  }

  async _step(delta) {
    const e = this._ents;
    const wc = e.weather && this._hass.states[e.weather]?.state === "on";
    if (wc && e.at0) {
      const s = this._hass.states[e.at0];
      const v = clamp((num(s) ?? 62) + delta, s?.attributes?.min ?? 50, s?.attributes?.max ?? 75);
      await this._call("number", "set_value", { entity_id: e.at0, value: v });
      await this._call("switch", "turn_on", { entity_id: e.weather }); // wymusza przeliczenie i zapis
    } else if (e.setpoint) {
      const s = this._hass.states[e.setpoint];
      const v = clamp((num(s) ?? 60) + delta, s?.attributes?.min ?? 55, s?.attributes?.max ?? 80);
      await this._call("number", "set_value", { entity_id: e.setpoint, value: v });
    }
  }

  async _toggleFeeder() {
    const id = this._ents.feeder;
    if (!id) return;
    const on = this._hass.states[id]?.state !== "off";
    // eslint-disable-next-line no-alert
    if (!window.confirm(on ? this._t.feederConfirmOff : this._t.feederConfirmOn)) return;
    await this._call("switch", on ? "turn_off" : "turn_on", { entity_id: id });
  }

  _onClick(ev) {
    const el = ev.composedPath().find((n) => n?.dataset?.act);
    if (!el) return;
    const act = el.dataset.act;
    if (act === "minus") this._step(-1);
    else if (act === "plus") this._step(1);
    else if (act === "weather") this._call("switch", "toggle", { entity_id: this._ents.weather });
    else if (act === "feeder") this._toggleFeeder();
    else if (act === "info") this._moreInfo(el.dataset.entity);
  }

  // ------------------------------------------------------------------ render
  _fmtTime(s) {
    if (!s || !s.state || ["unknown", "unavailable"].includes(s.state)) return "–";
    const d = new Date(s.state);
    if (Number.isNaN(d.getTime())) return "–";
    const lang = this._hass.locale?.language || this._hass.language || "pl";
    const day = d.toLocaleDateString(lang, { weekday: "short" }).replace(/\.$/, "");
    const time = d.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
    return `${day} ${time}`;
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    }
    const lang = (this._hass.locale?.language || this._hass.language || "pl").startsWith("pl") ? "pl" : "en";
    this._t = T[lang];
    const t = this._t;
    const devId = this._deviceId();
    const e = (this._ents = devId ? this._entities(devId) : {});
    const S = (k) => (e[k] ? this._hass.states[e[k]] : undefined);

    // Odśwież tylko gdy zmienił się któryś stan – inaczej animacje by się restartowały.
    const key = [devId, lang, JSON.stringify(this._config), ...Object.keys(KEYS).map((k) => S(k)?.last_updated)].join("|");
    if (key === this._key) return;
    this._key = key;

    if (!devId || !e.boiler) {
      this.shadowRoot.innerHTML = `<ha-card><div style="padding:16px">${esc(t.noDevice)}</div></ha-card>`;
      return;
    }

    const dev = this._hass.devices?.[devId];
    const title = this._config.title || dev?.name_by_user || dev?.name || "Compit";
    const subtitle = this._config.subtitle ?? "";
    const k = num(S("boiler")) ?? 0;
    const rr = num(S("ret")) ?? 0;
    const zad = num(S("setpoint"));
    const fuel = clamp(num(S("fuelPct")) ?? 0, 0, 100);
    const pump = S("pump")?.state === "on";
    const hot = pump || k >= 35;
    const hasWc = !!e.weather;
    const wc = S("weather")?.state === "on";
    const hasFeed = !!e.feeder;
    const feed = S("feeder")?.state !== "off";
    const kg = num(S("fuelKg"));
    const kgd = S("burn")?.attributes?.kg_per_day;
    const wt = S("weatherTarget");
    const tout = wt?.attributes?.outdoor_now;
    const wyl = num(wt);
    const tl = this._fmtTime(S("refillAt"));
    const tk = this._fmtTime(S("emptyAt"));

    const ca = pump ? "#ff7043" : hot ? "#ffd54f" : "#757575";
    const stt = pump ? t.heating : hot ? t.hot : t.cold;
    const fcol = fuel < 15 ? "#E53935" : fuel < 25 ? "#ffd54f" : "#81c784";
    const rcol = rr < 45 ? "#ffd54f" : "#4fc3f7";
    const chipW = stt.length * 9.6 + 28;
    const fh = (126 * fuel) / 100;
    const sx = zad == null ? null : 358 + clamp(zad / 90, 0, 1) * 124;
    const info = (ent) => (ent ? `data-act="info" data-entity="${esc(ent)}" class="tap"` : "");

    // Panel prawy – układ zależny od tego, czy są pogodówka i podajnik.
    let y = 234;
    let pills = "";
    if (hasWc) {
      pills += `
        <g data-act="weather" class="tap">
          <rect x="358" y="${y}" width="124" height="30" rx="15" fill="${wc ? "#81c784" : "#fff"}" fill-opacity="${wc ? 0.15 : 0.05}" stroke="${wc ? "#81c784" : "#fff"}" stroke-opacity="${wc ? 0.6 : 0.2}"/>
          <circle cx="376" cy="${y + 15}" r="5" fill="${wc ? "#81c784" : "#616161"}"/>
          <text x="428" y="${y + 19}" fill="${wc ? "#81c784" : "#9e9e9e"}" font-size="11" font-weight="bold" letter-spacing=".6" text-anchor="middle">${t.weather} ${wc ? t.on : t.off}</text>
        </g>
        ${tout != null ? `<text x="358" y="${y + 46}" fill="#7d7d7d" font-size="11">${t.outdoor} ${Number(tout).toFixed(1)}°${wyl != null ? ` · ${t.curve} ${wyl}°` : ""}</text>` : ""}`;
      y += 60;
    }
    pills += `<line x1="358" y1="${y}" x2="482" y2="${y}" stroke="#fff" stroke-opacity=".08"/>`;
    y += 8;
    if (hasFeed) {
      pills += `
        <g data-act="feeder" class="tap">
          <rect x="358" y="${y}" width="124" height="30" rx="15" fill="${feed ? "#81c784" : "#E53935"}" fill-opacity="${feed ? 0.15 : 0.25}" stroke="${feed ? "#81c784" : "#E53935"}" stroke-opacity=".6"/>
          <circle cx="376" cy="${y + 15}" r="5" fill="${feed ? "#81c784" : "#E53935"}">${feed ? "" : `<animate attributeName="opacity" values="1;.2;1" dur="1.2s" repeatCount="indefinite"/>`}</circle>
          <text x="428" y="${y + 19}" fill="${feed ? "#81c784" : "#ff8a80"}" font-size="11" font-weight="bold" letter-spacing=".6" text-anchor="middle">${t.feeder} ${feed ? t.on : t.off}</text>
        </g>`;
      y += 38;
    }

    const svg = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 528">
<defs>
<linearGradient id="cs" x1="0" x2="1"><stop offset="0" stop-color="#256b2a"/><stop offset=".5" stop-color="#3a9440"/><stop offset="1" stop-color="#22622a"/></linearGradient>
<linearGradient id="cs2" x1="0" x2="1"><stop offset="0" stop-color="#2a7030"/><stop offset="1" stop-color="#1e5a24"/></linearGradient>
<linearGradient id="dr" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#4a4f52"/><stop offset="1" stop-color="#2c3033"/></linearGradient>
<radialGradient id="fire" cx=".5" cy=".85" r=".8"><stop offset="0" stop-color="#fff3b0"/><stop offset=".35" stop-color="#ffb300"/><stop offset=".7" stop-color="#ff5722"/><stop offset="1" stop-color="#3e0d00"/></radialGradient>
<linearGradient id="gk" x1="0" x2="1"><stop offset="0" stop-color="#4fc3f7"/><stop offset=".5" stop-color="#ffd54f"/><stop offset="1" stop-color="#ff7043"/></linearGradient>
<pattern id="coal" width="14" height="12" patternUnits="userSpaceOnUse"><rect width="14" height="12" fill="#1b1b1b"/><path d="M1 4l3-3 4 1 1 4-3 3-4-1z" fill="#2f2f2f"/><path d="M8 9l3-2 3 2-1 3h-4z" fill="#353535"/><circle cx="11" cy="3" r="1.6" fill="#262626"/></pattern>
<clipPath id="hopclip"><rect x="252" y="196" width="70" height="126" rx="4"/></clipPath>
<clipPath id="winclip"><rect x="88" y="296" width="96" height="40" rx="6"/></clipPath>
</defs>

<text x="20" y="30" fill="var(--primary-text-color,#e0e0e0)" font-size="19" font-weight="bold">${esc(title)}</text>
${subtitle ? `<text x="20" y="50" fill="var(--secondary-text-color,#7d7d7d)" font-size="12">${esc(subtitle)}</text>` : ""}
<rect x="${486 - chipW}" y="14" width="${chipW}" height="26" rx="13" fill="${ca}" fill-opacity=".14" stroke="${ca}" stroke-opacity=".5"/>
<text x="${486 - chipW / 2}" y="32" fill="${ca}" font-size="13" font-weight="bold" letter-spacing=".6" text-anchor="middle">${stt}</text>

<rect x="178" y="66" width="26" height="34" fill="#5a5f63" stroke="#3a3e41"/>
<rect x="174" y="62" width="34" height="8" rx="2" fill="#6b7175"/>
${hot ? `<g fill="#bdbdbd">
<circle cx="191" cy="56" r="6"><animate attributeName="cy" values="58;24" dur="3s" repeatCount="indefinite"/><animate attributeName="r" values="5;12" dur="3s" repeatCount="indefinite"/><animate attributeName="opacity" values=".35;0" dur="3s" repeatCount="indefinite"/></circle>
<circle cx="196" cy="56" r="6"><animate attributeName="cy" values="58;22" dur="3s" begin="1s" repeatCount="indefinite"/><animate attributeName="r" values="4;11" dur="3s" begin="1s" repeatCount="indefinite"/><animate attributeName="opacity" values=".3;0" dur="3s" begin="1s" repeatCount="indefinite"/></circle>
<circle cx="187" cy="56" r="6"><animate attributeName="cy" values="58;26" dur="3s" begin="2s" repeatCount="indefinite"/><animate attributeName="r" values="4;10" dur="3s" begin="2s" repeatCount="indefinite"/><animate attributeName="opacity" values=".3;0" dur="3s" begin="2s" repeatCount="indefinite"/></circle>
</g>` : ""}

<g ${info(e.boiler)}>
<rect x="48" y="98" width="176" height="408" rx="6" fill="url(#cs)" stroke="#174d1c"/>
<rect x="48" y="98" width="176" height="10" rx="4" fill="#4caf50" fill-opacity=".35"/>
<rect x="150" y="118" width="62" height="36" rx="4" fill="#1d1f21" stroke="#0d0f10"/>
<rect x="156" y="123" width="50" height="20" rx="2" fill="#0f2a14"/>
<text x="181" y="138" fill="#7CFC8A" font-size="13" font-weight="bold" text-anchor="middle" font-family="monospace">${Math.round(k)}°</text>
<circle cx="160" cy="149" r="2" fill="${pump ? "#4fc3f7" : "#455a64"}"/><circle cx="168" cy="149" r="2" fill="${hot ? "#ff7043" : "#455a64"}"/>
<rect x="70" y="166" width="132" height="96" rx="6" fill="url(#dr)" stroke="#1a1c1e"/>
<rect x="196" y="196" width="8" height="34" rx="3" fill="#9e9e9e"/>
<rect x="80" y="284" width="112" height="62" rx="6" fill="url(#dr)" stroke="#1a1c1e"/>
<rect x="88" y="296" width="96" height="40" rx="6" fill="#120804"/>
<g clip-path="url(#winclip)">${hot ? `
<rect x="88" y="296" width="96" height="40" fill="url(#fire)" opacity="${pump ? 0.95 : 0.55}"><animate attributeName="opacity" values="${pump ? "0.85;1;0.75;0.95;0.85" : "0.45;0.6;0.4;0.55;0.45"}" dur="1.3s" repeatCount="indefinite"/></rect>
<path d="M96 336 q6 -18 12 -6 q4 -16 10 -2 q6 -20 12 -4 q5 -14 10 0 q6 -18 12 -4 q4 -12 10 2 q5 -10 10 14z" fill="#ffcc80" opacity=".7"><animateTransform attributeName="transform" type="translate" values="0 0;0 -3;0 1;0 -2;0 0" dur=".9s" repeatCount="indefinite"/></path>
<path d="M100 336 q8 -12 14 -2 q6 -14 12 0 q6 -12 12 -1 q6 -14 12 0 q6 -10 12 3z" fill="#fff8e1" opacity=".55"><animateTransform attributeName="transform" type="translate" values="0 0;0 -2;0 1;0 -3;0 0" dur=".7s" repeatCount="indefinite"/></path>` : ""}
</g>
<rect x="88" y="296" width="96" height="40" rx="6" fill="none" stroke="#000" stroke-opacity=".6"/>
<rect x="70" y="372" width="132" height="104" rx="6" fill="url(#dr)" stroke="#1a1c1e"/>
<rect x="196" y="408" width="8" height="34" rx="3" fill="#9e9e9e"/>
<text x="136" y="430" fill="#fff" fill-opacity=".18" font-size="11" text-anchor="middle" letter-spacing="1">${t.ash}</text>
</g>
<rect x="54" y="506" width="14" height="8" fill="#1c1c1c"/><rect x="204" y="506" width="14" height="8" fill="#1c1c1c"/>

<g ${info(e.fuelKg || e.fuelPct)}>
<rect x="238" y="130" width="98" height="376" rx="5" fill="url(#cs2)" stroke="#174d1c"/>
<rect x="234" y="124" width="106" height="14" rx="4" fill="#2f7a35" stroke="#174d1c"/>
<rect x="280" y="118" width="16" height="8" rx="2" fill="#9e9e9e"/>
<rect x="250" y="194" width="74" height="130" rx="6" fill="#0c0c0c" stroke="#0a2e0e" stroke-width="2"/>
<g clip-path="url(#hopclip)">
<rect x="252" y="${(322 - fh).toFixed(1)}" width="70" height="${fh.toFixed(1)}" fill="url(#coal)"/>
<path d="M252 ${(322 - fh).toFixed(1)} l8 -4 l9 3 l10 -5 l9 4 l11 -3 l8 4 l9 -2 l6 3 v6 h-70z" fill="url(#coal)"/>
<rect x="252" y="${(322 - fh).toFixed(1)}" width="70" height="${fh.toFixed(1)}" fill="${fcol}" fill-opacity=".10"/>
</g>
${[25, 50, 75].map((p) => `<line x1="250" y1="${322 - 1.26 * p}" x2="258" y2="${322 - 1.26 * p}" stroke="#9e9e9e" stroke-opacity=".5"/>`).join("")}
<text x="287" y="186" fill="${fcol}" font-size="16" font-weight="bold" text-anchor="middle">${Math.round(fuel)}%</text>
<rect x="246" y="344" width="82" height="150" rx="5" fill="#215e27" stroke="#174d1c"/>
<line x1="256" y1="360" x2="318" y2="360" stroke="#000" stroke-opacity=".25"/><line x1="256" y1="370" x2="318" y2="370" stroke="#000" stroke-opacity=".25"/><line x1="256" y1="380" x2="318" y2="380" stroke="#000" stroke-opacity=".25"/>
</g>
<rect x="222" y="420" width="40" height="16" rx="2" fill="#5d6266" stroke="#2b2e30">${hot && feed ? `<animate attributeName="x" values="222;212;222" dur="${pump ? "4s" : "9s"}" repeatCount="indefinite"/>` : ""}</rect>
<g transform="translate(287 462)">
<circle r="20" fill="#111" stroke="#3a3e41" stroke-width="2"/>
<g fill="${pump ? "#4fc3f7" : "#616161"}">${hot ? `<animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="${pump ? "0.6s" : "2.5s"}" repeatCount="indefinite"/>` : ""}
<path d="M0 0 C4 -6 3 -14 0 -16 C-4 -12 -3 -6 0 0z"/><path d="M0 0 C6 4 14 3 16 0 C12 -4 6 -3 0 0z"/><path d="M0 0 C-4 6 -3 14 0 16 C4 12 3 6 0 0z"/><path d="M0 0 C-6 -4 -14 -3 -16 0 C-12 4 -6 3 0 0z"/>
</g><circle r="3" fill="#bdbdbd"/></g>
<rect x="240" y="506" width="12" height="8" fill="#1c1c1c"/><rect x="322" y="506" width="12" height="8" fill="#1c1c1c"/>
<rect x="36" y="514" width="310" height="4" rx="2" fill="#000" fill-opacity=".35"/>

<path d="M206 112 H340" stroke="#ff7043" stroke-opacity=".35" stroke-width="9" fill="none" stroke-linecap="round"/>
<path d="M206 112 H340" stroke="#ff8a65" stroke-width="3" fill="none" stroke-dasharray="8 10" stroke-linecap="round">${pump ? `<animate attributeName="stroke-dashoffset" values="36;0" dur="1s" repeatCount="indefinite"/>` : ""}</path>
<path d="M342 498 H222" stroke="#4fc3f7" stroke-opacity=".35" stroke-width="9" fill="none" stroke-linecap="round"/>
<path d="M342 498 H222" stroke="#81d4fa" stroke-width="3" fill="none" stroke-dasharray="8 10" stroke-linecap="round">${pump ? `<animate attributeName="stroke-dashoffset" values="36;0" dur="1s" repeatCount="indefinite"/>` : ""}</path>

<g ${info(e.boiler)}>
<rect x="352" y="76" width="136" height="84" fill="transparent"/>
<text x="358" y="92" fill="#9e9e9e" font-size="11" letter-spacing=".8">${t.boiler}</text>
<text x="358" y="134" fill="${hot ? ca : "#e0e0e0"}" font-size="44" font-weight="bold">${Math.round(k)}°</text>
<rect x="358" y="146" width="124" height="7" rx="3.5" fill="#fff" fill-opacity=".07"/>
<rect x="358" y="146" width="${(clamp(k / 90, 0.03, 1) * 124).toFixed(1)}" height="7" rx="3.5" fill="url(#gk)"/>
${sx != null ? `<line x1="${sx.toFixed(1)}" y1="142" x2="${sx.toFixed(1)}" y2="157" stroke="#fff" stroke-width="2"/>` : ""}
</g>

<text x="358" y="184" fill="${wc ? "#81c784" : "#9e9e9e"}" font-size="11" letter-spacing=".8">${t.setpoint}${wc ? ` · ${t.auto}` : ""}</text>
<g data-act="minus" class="tap"><circle cx="372" cy="208" r="14" fill="#fff" fill-opacity=".06" stroke="#fff" stroke-opacity=".25"/><text x="372" y="214" fill="#e0e0e0" font-size="20" font-weight="bold" text-anchor="middle">−</text></g>
<text x="420" y="216" fill="${wc ? "#81c784" : "#e0e0e0"}" font-size="24" font-weight="bold" text-anchor="middle" ${info(e.setpoint)}>${zad == null ? "–" : Math.round(zad)}°</text>
<g data-act="plus" class="tap"><circle cx="468" cy="208" r="14" fill="#fff" fill-opacity=".06" stroke="#fff" stroke-opacity=".25"/><text x="468" y="214" fill="#e0e0e0" font-size="20" font-weight="bold" text-anchor="middle">+</text></g>

${pills}
<g ${info(e.pump)}>
<rect x="352" y="${y}" width="136" height="20" fill="transparent"/>
<text x="358" y="${y + 14}" fill="#9e9e9e" font-size="11" letter-spacing=".8">${t.pump}</text>
<text x="482" y="${y + 15}" fill="${pump ? "#4fc3f7" : "#7d7d7d"}" font-size="13" font-weight="bold" text-anchor="end">${pump ? t.running : t.stopped}</text>
</g>

<g ${info(e.fuelKg || e.fuelPct)}>
<rect x="352" y="370" width="136" height="104" fill="transparent"/>
<line x1="358" y1="366" x2="482" y2="366" stroke="#fff" stroke-opacity=".08"/>
<text x="358" y="382" fill="#9e9e9e" font-size="11" letter-spacing=".8">${t.fuel}</text>
<text x="482" y="384" fill="${fcol}" font-size="18" font-weight="bold" text-anchor="end">${kg != null ? `${Math.round(kg)} kg` : `${Math.round(fuel)}%`}</text>
<rect x="358" y="392" width="124" height="8" rx="4" fill="#fff" fill-opacity=".07"/>
<rect x="358" y="392" width="${(clamp(fuel / 100, 0.03, 1) * 124).toFixed(1)}" height="8" rx="4" fill="${fcol}"/>
${kgd != null ? `<text x="358" y="424" fill="#9e9e9e" font-size="12">${t.burn}</text><text x="482" y="424" fill="#cfcfcf" font-size="12" text-anchor="end">${kgd} ${t.perDay}</text>` : ""}
${e.refillAt ? `<text x="358" y="446" fill="#9e9e9e" font-size="12">${t.refill}</text><text x="482" y="446" fill="${fuel < 10 ? "#E53935" : fuel < 25 ? "#ffd54f" : "#e0e0e0"}" font-size="12" font-weight="bold" text-anchor="end">${esc(tl)}</text>` : ""}
${e.emptyAt ? `<text x="358" y="468" fill="#9e9e9e" font-size="12">${t.empty}</text><text x="482" y="468" fill="${fuel < 10 ? "#E53935" : "#cfcfcf"}" font-size="12" text-anchor="end">${esc(tk)}</text>` : ""}
</g>

<g ${info(e.ret)}>
<rect x="352" y="474" width="136" height="50" fill="transparent"/>
<text x="358" y="486" fill="#9e9e9e" font-size="11" letter-spacing=".8">${t.ret}</text>
<text x="358" y="518" fill="${rcol}" font-size="32" font-weight="bold">${Math.round(rr)}°</text>
</g>
</svg>`;

    this.shadowRoot.innerHTML = `
<style>
  ha-card { overflow: hidden; }
  svg { display: block; width: 100%; height: auto; font-family: var(--ha-font-family-body, Roboto, Arial, sans-serif); }
  .tap { cursor: pointer; }
  .tap:hover { filter: brightness(1.15); }
</style>
<ha-card>${svg}</ha-card>`;
  }
}

if (!customElements.get("compit-boiler-card")) {
  customElements.define("compit-boiler-card", CompitBoilerCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "compit-boiler-card",
    name: "Kocioł Compit",
    description: "Animowany kocioł z podajnikiem: temperatury, zadana, sterowanie pogodowe, podajnik i opał.",
    preview: true,
    documentationURL: "https://github.com/xtronets/ha-compit-multi765",
  });
  // eslint-disable-next-line no-console
  console.info(`%c COMPIT-BOILER-CARD %c ${VERSION} `, "background:#2e7d32;color:#fff", "background:#333;color:#fff");
}
