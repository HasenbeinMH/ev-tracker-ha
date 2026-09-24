// Pruefstand fuer den Node-RED-Flow (vorlagen/node-red/ev_pv_anteil_flow.json).
// Fuehrt die beiden Funktionsknoten aus dem fertigen Flow aus, spielt Home Assistant
// nach (Zustaende lesen, gesendete Sensoren speichern) und gibt das Ergebnis als JSON aus.
//
//   node tests/vorlagen_nodered_pruefstand.js <flow.json> <szenario.json>
//
// Szenario: {einstellungen: {...}, env: {...}, dateispeicher: bool,
//            schritte: [{t: Sekunden, zustaende: {entity: {state, attributes}},
//                        nodered_neustart?: bool, ha_neustart?: bool}]}
const fs = require("fs");
const flowKnoten = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const sz = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

const code1 = flowKnoten.find(n => n.type === "function" && n.name.startsWith("⚙")).func
    .replace("const cfg = EINSTELLUNGEN;", "const cfg = Object.assign(EINSTELLUNGEN, __einstellungen);");
const code2 = flowKnoten.find(n => n.type === "function" && n.name === "PV / Netz berechnen").func;
const knoten1 = new Function("msg", "node", "context", "flow", "global", "env", "__einstellungen", code1);
const knoten2 = new Function("msg", "node", "context", "flow", "global", "env", code2);

let jetzt = 0;
Date.now = () => jetzt;

const flowSpeicher = {};
const flow = {get: k => flowSpeicher[k], set: (k, v) => { flowSpeicher[k] = v; }};
const env = {get: k => (sz.env || {})[k]};
function kontext() {
    const speicher = {memory: {}, file: {}};
    return {
        speicher,
        get(k, s = "memory") {
            if (s === "file" && !sz.dateispeicher) throw new Error("Unknown context store 'file'");
            return JSON.parse(JSON.stringify(speicher[s][k] ?? null));
        },
        set(k, v, s = "memory") {
            if (s === "file" && !sz.dateispeicher) throw new Error("Unknown context store 'file'");
            speicher[s][k] = JSON.parse(JSON.stringify(v));
        },
    };
}
const kontext1 = kontext(), kontext2 = kontext();
const status = {k1: null, k2: null};
const node1 = {status: s => { status.k1 = s; }}, node2 = {status: s => { status.k2 = s; }};

let ha = {};           // von HA gespeicherte Zustaende der vom Flow geschriebenen Sensoren
const posts = [];
const ergebnis = [];

for (const schritt of sz.schritte) {
    jetzt = schritt.t * 1000;
    if (schritt.nodered_neustart) kontext2.speicher.memory = {};
    if (schritt.ha_neustart) ha = {};
    const aus1 = knoten1({payload: jetzt}, node1, kontext1, flow, {}, env, sz.einstellungen || {});
    let schrittPosts = [];
    if (aus1) {
        const anfragen = aus1[0];
        // HTTP-Request: GET /api/states/<entity>
        const antworten = anfragen.map(m => {
            const entity = m.url.split("/api/states/")[1];
            const s = (schritt.zustaende || {})[entity] ?? ha[entity];
            if (!m.headers.Authorization.startsWith("Bearer ")) throw new Error("kein Token");
            return s ? {entity_id: entity, ...s} : {message: "Entity not found."};
        });
        const aus2 = knoten2({payload: antworten}, node2, kontext2, flow, {}, env);
        if (aus2) {
            for (const m of aus2[0]) {
                if (m.method !== "POST") throw new Error("erwartet POST");
                const entity = m.url.split("/api/states/")[1];
                ha[entity] = {state: String(m.payload.state), attributes: m.payload.attributes};
                schrittPosts.push(entity);
            }
        }
    }
    posts.push(schrittPosts);
    ergebnis.push({t: schritt.t, status1: status.k1, status2: status.k2,
                   ha: JSON.parse(JSON.stringify(ha)), gesendet: schrittPosts});
}
process.stdout.write(JSON.stringify(ergebnis));
