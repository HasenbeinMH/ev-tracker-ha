/* Zeichnet die Dashboard-Charts mit Apache ECharts.
 * Die Optionen kommen fertig aus charts.py als JSON (<script type="application/json">).
 * Strings "fn:<name>" werden durch Formatierfunktionen ersetzt, "fn:<name>:ap" durch
 * eine Variante fuer axisPointer-Labels (die bekommen ein Objekt statt eines Werts). */
(function () {
  "use strict";

  const zahlFormat = (min, max) =>
    new Intl.NumberFormat("de-DE", { minimumFractionDigits: min, maximumFractionDigits: max });
  const f0 = zahlFormat(0, 0), f1 = zahlFormat(1, 1), f2 = zahlFormat(2, 2), fFrei = zahlFormat(0, 2);

  const zweistellig = (n) => String(n).padStart(2, "0");
  function alsDatum(v) {
    if (typeof v === "number") return new Date(v);
    const [j, m, t] = String(v).split("-").map(Number);
    return new Date(j, (m || 1) - 1, t || 1);
  }

  const FORMAT = {
    zahl: (v) => fFrei.format(v),
    zahl1: (v) => f1.format(v),
    zahl2: (v) => f2.format(v),
    euro0: (v) => f0.format(v) + " €",
    euro2: (v) => f2.format(v) + " €",
    euroLiter: (v) => f2.format(v) + " €/L",
    ctKwh: (v) => f2.format(v) + " ct/kWh",
    kg1: (v) => f1.format(v) + " kg",
    kwh100: (v) => f1.format(v) + " kWh/100 km",
    monat: (v) => { const s = String(v); return s.slice(5, 7) + "/" + s.slice(0, 4); },
    datumMonat: (v) => { const d = alsDatum(v); return zweistellig(d.getMonth() + 1) + "/" + d.getFullYear(); },
    datum: (v) => { const d = alsDatum(v); return zweistellig(d.getDate()) + "." + zweistellig(d.getMonth() + 1) + "." + d.getFullYear(); },
    // Schieberegler: bei Kategorien kommt der Wert als zweites Argument
    zoomMonat: (v, s) => FORMAT.monat(s || v),
    zoomDatum: (v, s) => FORMAT.datum(s || v),
    labelEuro0: (p) => f0.format(p.value) + " €",
    labelCt: (p) => f1.format(Array.isArray(p.value) ? p.value[1] : p.value),
    labelRef: (p) => f1.format(p.value) + " kWh Ref.",
    labelAnteil: (p) => p.name + "\n" + f1.format(p.percent) + " %",
    tooltipAnteil: (p) => p.marker + p.name + ": <b>" + f2.format(p.value) + " €</b> (" + f1.format(p.percent) + " %)",
  };

  function aufloesen(wert) {
    if (typeof wert === "string" && wert.startsWith("fn:")) {
      const [, name, variante] = wert.split(":");
      const fn = FORMAT[name];
      if (!fn) { console.warn("Unbekannter Formatierer:", name); return undefined; }
      return variante === "ap" ? (p) => fn(p.value) : fn;
    }
    if (Array.isArray(wert)) return wert.map(aufloesen);
    if (wert && typeof wert === "object") {
      for (const k of Object.keys(wert)) wert[k] = aufloesen(wert[k]);
    }
    return wert;
  }

  const instanzen = [];

  document.querySelectorAll("[data-echart]").forEach((el) => {
    const quelle = document.getElementById(el.dataset.echart);
    const option = JSON.parse(quelle.textContent);
    if (option.leer) {
      el.classList.add("echart-leer");
      el.textContent = option.leer;
      return;
    }
    const chart = echarts.init(el, null, { renderer: "canvas" });
    chart.setOption(aufloesen(option));
    instanzen.push(chart);
  });

  let timer;
  window.addEventListener("resize", () => {
    clearTimeout(timer);
    timer = setTimeout(() => instanzen.forEach((c) => c.resize()), 120);
  });
})();
