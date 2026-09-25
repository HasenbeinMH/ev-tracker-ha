// ═══════════════════════════════════════════════════════════════════════════
//  EV Tracker – PV-Anteil beim Laden · EINSTELLUNGEN
//  Nur diesen Block anpassen, dann oben rechts "Übernehmen" (Deploy).
// ═══════════════════════════════════════════════════════════════════════════
const EINSTELLUNGEN = {
    // Netzleistung (W oder kW – wird erkannt).
    netz: "sensor.DEIN_NETZ",
    // true: positiver Wert = Bezug aus dem Netz, negativ = Einspeisung.
    // false: umgekehrt (z.B. viele SolarEdge-Zähler: positiv = Einspeisung).
    netz_bezug_positiv: true,

    // Ladeleistung der Wallbox (W oder kW).
    wallbox: "sensor.DEINE_WALLBOX",

    // Optional, empfohlen: Energiezähler der Wallbox (kWh oder Wh). Dann wird dieser
    // Zähler aufgeteilt – genauer als die Leistung aufzusummieren. Sonst "".
    wallbox_zaehler: "",

    // Hausakku-Entladung ins Auto zählt als "pv" (Akku lädt nur mit Solarstrom)
    // oder "netz" (Akku lädt auch aus dem Netz). Ohne Akku egal.
    akku_als: "pv",
    // Nur bei akku_als "netz": Akku-Leistung (W/kW) und Vorzeichen der Entladung.
    akku: "",
    akku_entladung_positiv: true,

    // Unter dieser Leistung gilt die Wallbox als aus (Standby).
    standby_w: 50,

    // Home Assistant: im Node-RED-Add-on leer lassen – der Zugang kommt automatisch.
    // Sonst z.B. "http://192.168.0.10:8123" und ein langlebiges Zugriffstoken.
    ha_url: "",
    ha_token: "",

    // Namen der Sensoren, die dieser Flow in Home Assistant anlegt.
    sensor_pv: "sensor.ev_ladung_pv",
    sensor_netz: "sensor.ev_ladung_netz",
    sensor_pv_leistung: "sensor.ev_ladeleistung_pv",
    sensor_netz_leistung: "sensor.ev_ladeleistung_netz",
};
// ═══ Ab hier nichts mehr ändern ═══════════════════════════════════════════

const cfg = EINSTELLUNGEN;
const basis = (cfg.ha_url || "http://supervisor/core").replace(/\/+$/, "");
const token = cfg.ha_token || env.get("SUPERVISOR_TOKEN");
if (!token) {
    node.status({fill: "red", shape: "ring",
                 text: "Kein Zugang zu HA: ha_url und ha_token eintragen"});
    return null;
}
for (const feld of ["netz", "wallbox"]) {
    if (!cfg[feld] || cfg[feld].includes("DEIN")) {
        node.status({fill: "red", shape: "ring", text: `Sensor "${feld}" eintragen`});
        return null;
    }
}

// Welche Zustaende pro Durchlauf gelesen werden (Reihenfolge = Rollen)
const rollen = [["netz", cfg.netz], ["wallbox", cfg.wallbox],
                ["eigen_pv", cfg.sensor_pv], ["eigen_netz", cfg.sensor_netz]];
if (cfg.wallbox_zaehler) rollen.push(["zaehler", cfg.wallbox_zaehler]);
if (cfg.akku_als === "netz" && cfg.akku) rollen.push(["akku", cfg.akku]);

flow.set("ev_pv_cfg", {...cfg, basis, token, rollen: rollen.map(r => r[0])});

const kopf = {Authorization: "Bearer " + token, "Content-Type": "application/json"};
const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
node.status({fill: "green", shape: "dot", text: `liest ${rollen.length} Sensoren`});
return [rollen.map(([rolle, entity], i) => ({
    url: `${basis}/api/states/${entity}`,
    method: "GET",
    headers: kopf,
    rolle,
    parts: {id, index: i, count: rollen.length, type: "array", len: 1},
}))];
