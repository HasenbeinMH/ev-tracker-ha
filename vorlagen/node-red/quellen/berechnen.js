// EV Tracker – PV-Anteil beim Laden · BERECHNUNG (nichts ändern, Einstellungen oben)
//
// Regel "Haus zuerst, das Auto bekommt den Ueberschuss":
//   Netz ins Auto = min(Netzbezug, Wallbox-Leistung),  PV ins Auto = Rest
// Ein Hausakku, der ins Auto entlaedt, senkt den Netzbezug und zaehlt damit als PV
// (Einstellung akku_als "netz": Akku-Entladung wird zum Netzbezug gerechnet).
//
// kWh: mit Wallbox-Zaehler wird jeder Zaehleranstieg nach dem mittleren PV-Anteil
// seit dem letzten Anstieg aufgeteilt; ohne Zaehler wird die Leistung aufsummiert.

const cfg = flow.get("ev_pv_cfg");
if (!cfg || !Array.isArray(msg.payload)) return null;

// Antworten den Rollen zuordnen (Reihenfolge wie im Einstellungs-Knoten)
const st = {};
cfg.rollen.forEach((rolle, i) => { st[rolle] = msg.payload[i]; });

function zahl(s) {
    if (!s || s.state === undefined) return null;
    const v = parseFloat(s.state);
    return Number.isFinite(v) ? v : null;
}
function einheit(s) {
    return ((s && s.attributes && s.attributes.unit_of_measurement) || "").trim();
}
function watt(s) {
    const v = zahl(s);
    if (v === null) return null;
    const e = einheit(s);
    return e === "kW" ? v * 1000 : e === "MW" ? v * 1e6 : v;
}
function kwh(s) {
    const v = zahl(s);
    if (v === null) return null;
    const e = einheit(s);
    return e === "Wh" ? v / 1000 : e === "MWh" ? v * 1000 : v;
}

// ── Zustand (in "file" gespeichert, wenn eingerichtet – sonst im Speicher) ────
function laden() {
    try { return context.get("zaehler", "file"); } catch (e) { return context.get("zaehler"); }
}
function speichern(z) {
    try { context.set("zaehler", z, "file"); } catch (e) { context.set("zaehler", z); }
}
const jetzt = Date.now();
let z = laden();
if (!z) {
    // Erster Lauf oder Neustart ohne Dateispeicher: Stand aus den eigenen HA-Sensoren
    // uebernehmen. Nur dann – im laufenden Betrieb waeren die gesendeten Werte gerundet
    // und wuerden den Zaehler bei jedem Durchlauf ein wenig nach oben ziehen.
    z = {pv: kwh(st.eigen_pv) || 0, netz: kwh(st.eigen_netz) || 0, t: null, zaehler: null,
         anteil_summe: 0, dauer_summe: 0, anteil_letzt: 0, gesendet: {}};
}

// ── Momentane Aufteilung ─────────────────────────────────────────────────────
const netz_roh = watt(st.netz), wb_roh = watt(st.wallbox);
if (netz_roh === null || wb_roh === null) {
    const [fehlt, antwort] = netz_roh === null ? [cfg.netz, st.netz] : [cfg.wallbox, st.wallbox];
    // HA antwortet bei unbekannter Entity mit {"message": "Entity not found."}
    const grund = (antwort && (antwort.message || antwort.state)) || "keine Antwort";
    node.status({fill: "yellow", shape: "ring", text: `${fehlt}: ${grund}`});
    z.t = jetzt;                    // keine grosse Luecke integrieren
    speichern(z);
    return null;
}
const wb = wb_roh < cfg.standby_w ? 0 : wb_roh;
let bezug = Math.max(0, cfg.netz_bezug_positiv ? netz_roh : -netz_roh);
if (cfg.akku_als === "netz" && st.akku) {
    const akku = watt(st.akku);
    if (akku !== null) bezug += Math.max(0, cfg.akku_entladung_positiv ? akku : -akku);
}
const netz_w = Math.min(bezug, wb);
const pv_w = wb - netz_w;
const anteil = wb > 0 ? pv_w / wb : null;

// ── kWh fortschreiben ────────────────────────────────────────────────────────
// Zeit seit dem letzten Durchlauf; nach laengerer Pause (Neustart) nicht integrieren
const dt = typeof z.t === "number" ? (jetzt - z.t) / 1000 : 0;
const dt_ok = dt > 0 && dt <= 120 ? dt : 0;
z.t = jetzt;

if (cfg.wallbox_zaehler) {
    const stand = kwh(st.zaehler);
    if (anteil !== null) {
        z.anteil_summe += anteil * dt_ok;
        z.dauer_summe += dt_ok;
        z.anteil_letzt = anteil;
    }
    if (stand !== null) {
        const delta = z.zaehler === null ? 0 : stand - z.zaehler;
        if (delta > 0 && delta <= 20) {
            // Mittlerer PV-Anteil seit dem letzten Zaehleranstieg
            const a = z.dauer_summe > 0 ? z.anteil_summe / z.dauer_summe : z.anteil_letzt;
            z.pv += delta * a;
            z.netz += delta * (1 - a);
            z.anteil_summe = 0;
            z.dauer_summe = 0;
        }
        // delta <= 0: unveraendert · delta > 20 kWh oder Zaehler zurueckgesetzt: neue Basis
        if (delta !== 0 || z.zaehler === null) z.zaehler = stand;
    }
} else {
    z.pv += pv_w * dt_ok / 3.6e6;
    z.netz += netz_w * dt_ok / 3.6e6;
}
speichern(z);

// ── Nach Home Assistant schreiben (bei Aenderung oder alle 5 Minuten) ──────────
const sensoren = [
    [cfg.sensor_pv, +z.pv.toFixed(3), "kWh", "energy", "total_increasing",
     "EV Ladung PV", "mdi:solar-power"],
    [cfg.sensor_netz, +z.netz.toFixed(3), "kWh", "energy", "total_increasing",
     "EV Ladung Netz", "mdi:transmission-tower"],
    [cfg.sensor_pv_leistung, Math.round(pv_w), "W", "power", "measurement",
     "EV Ladeleistung PV", "mdi:solar-power"],
    [cfg.sensor_netz_leistung, Math.round(netz_w), "W", "power", "measurement",
     "EV Ladeleistung Netz", "mdi:transmission-tower"],
];
z.gesendet = z.gesendet || {};
const raus = [];
for (const [entity, wert, e, klasse, art, name, icon] of sensoren) {
    const alt = z.gesendet[entity];
    if (alt && alt.wert === wert && jetzt - alt.zeit < 300000) continue;
    z.gesendet[entity] = {wert, zeit: jetzt};
    raus.push({
        url: `${cfg.basis}/api/states/${entity}`,
        method: "POST",
        headers: {Authorization: "Bearer " + cfg.token, "Content-Type": "application/json"},
        payload: {state: wert, attributes: {unit_of_measurement: e, device_class: klasse,
                  state_class: art, friendly_name: name, icon}},
    });
}
speichern(z);

const pct = anteil === null ? "–" : Math.round(anteil * 100) + " %";
node.status({fill: "green", shape: "dot",
             text: `PV ${Math.round(pv_w)} W · Netz ${Math.round(netz_w)} W (PV-Anteil ${pct}) · `
                 + `${z.pv.toFixed(2)} / ${z.netz.toFixed(2)} kWh`});
return [raus];
