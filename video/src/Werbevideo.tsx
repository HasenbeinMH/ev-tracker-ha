import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Easing,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

// ── Farben wie in der App ────────────────────────────────────────────────────
const C = {
  bg: '#0f1116',
  bg2: '#171a22',
  karte: '#1d212b',
  rand: '#2a2f3b',
  text: '#e8ebf1',
  leise: '#9aa3b2',
  blau: '#5aa0e6',
  gruen: '#62c584',
  orange: '#e8954a',
};
const SCHRIFT = '"Segoe UI", "Inter", system-ui, sans-serif';

// Aufnahmen: 1280 CSS-Pixel breit, dreifache Aufloesung
const DPR = 3;

// ── Szenen (Frames bei 30 fps) ───────────────────────────────────────────────
const S = {
  intro: [0, 150],
  dashboard: [150, 300],
  amortisation: [450, 300],
  diagramme: [750, 300],
  abo: [1050, 300],
  ha: [1350, 240],
  outro: [1590, 210],
} as const;
export const GESAMT = 1800;

const ease = Easing.bezier(0.45, 0, 0.2, 1);

// Ein- und Ausblenden je Szene
const useBlende = (dauer: number) => {
  const f = useCurrentFrame();
  return interpolate(f, [0, 14, dauer - 14, dauer], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
};

// ── Hintergrund ─────────────────────────────────────────────────────────────
const Hintergrund: React.FC = () => {
  const f = useCurrentFrame();
  const x = 30 + Math.sin(f / 140) * 12;
  const y = 20 + Math.cos(f / 170) * 10;
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(ellipse at ${x}% ${y}%, #1f3550 0%, ${C.bg} 55%),
                     radial-gradient(ellipse at 85% 90%, #1d3a2a 0%, transparent 45%)`,
        backgroundColor: C.bg,
      }}
    />
  );
};

// ── Ueberschrift oben ────────────────────────────────────────────────────────
const Titel: React.FC<{zeile: string; unter?: string; farbe?: string}> = ({zeile, unter, farbe}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: f - 4, fps, config: {damping: 200}});
  const s2 = spring({frame: f - 12, fps, config: {damping: 200}});
  return (
    <div style={{position: 'absolute', left: 200, top: 34, right: 200, fontFamily: SCHRIFT}}>
      <div
        style={{
          fontSize: 52,
          fontWeight: 700,
          color: C.text,
          letterSpacing: -0.5,
          opacity: s,
          transform: `translateY(${(1 - s) * 24}px)`,
        }}
      >
        <span style={{color: farbe ?? C.blau}}>▍</span>
        {zeile}
      </div>
      {unter && (
        <div
          style={{
            fontSize: 26,
            color: C.leise,
            marginTop: 6,
            marginLeft: 34,
            opacity: s2,
            transform: `translateY(${(1 - s2) * 16}px)`,
          }}
        >
          {unter}
        </div>
      )}
    </div>
  );
};

// ── Browserfenster mit Kamerafahrt ueber eine Aufnahme ──────────────────────
type Kamera = {x: number; y: number; w: number}; // CSS-Pixel der Aufnahme
const FENSTER = {x: 200, y: 168, w: 1520, h: 860};
const LEISTE = 34;
const BILD_H = FENSTER.h - LEISTE;

const kameraBei = (frame: number, punkte: [number, Kamera][]): Kamera => {
  const frames = punkte.map((p) => p[0]);
  const wert = (k: keyof Kamera) =>
    interpolate(frame, frames, punkte.map((p) => p[1][k]), {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: ease,
    });
  return {x: wert('x'), y: wert('y'), w: wert('w')};
};

// CSS-Rechteck der Aufnahme -> Pixel im Bildbereich des Fensters
const aufFenster = (k: Kamera, r: {x: number; y: number; w: number; h: number}) => {
  const m = FENSTER.w / k.w;
  return {left: (r.x - k.x) * m, top: (r.y - k.y) * m, width: r.w * m, height: r.h * m};
};

const Aufnahme: React.FC<{
  bild: string;
  kamera: Kamera;
  url: string;
  ueberblende?: {bild: string; ab: number; dauer: number};
  markierungen?: {r: {x: number; y: number; w: number; h: number}; ab: number; farbe?: string}[];
}> = ({bild, kamera, url, ueberblende, markierungen}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const m = FENSTER.w / (kamera.w * DPR);
  const bildStil: React.CSSProperties = {
    position: 'absolute',
    left: 0,
    top: 0,
    transformOrigin: '0 0',
    transform: `scale(${m}) translate(${-kamera.x * DPR}px, ${-kamera.y * DPR}px)`,
  };
  const einflug = spring({frame: f, fps, config: {damping: 200}});
  const ueber = ueberblende
    ? interpolate(f, [ueberblende.ab, ueberblende.ab + ueberblende.dauer], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      })
    : 0;
  return (
    <div
      style={{
        position: 'absolute',
        left: FENSTER.x,
        top: FENSTER.y,
        width: FENSTER.w,
        height: FENSTER.h,
        borderRadius: 14,
        overflow: 'hidden',
        background: C.bg,
        border: `1px solid ${C.rand}`,
        boxShadow: '0 30px 80px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.03)',
        transform: `translateY(${(1 - einflug) * 40}px) scale(${0.97 + 0.03 * einflug})`,
      }}
    >
      <div
        style={{
          height: LEISTE,
          background: '#232733',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '0 14px',
          fontFamily: SCHRIFT,
        }}
      >
        {['#ef6b5e', '#f4bf4f', '#61c554'].map((c) => (
          <div key={c} style={{width: 12, height: 12, borderRadius: 6, background: c}} />
        ))}
        <div
          style={{
            marginLeft: 18,
            flex: 1,
            maxWidth: 560,
            height: 22,
            borderRadius: 6,
            background: '#161921',
            color: C.leise,
            fontSize: 14,
            lineHeight: '22px',
            padding: '0 12px',
          }}
        >
          {url}
        </div>
      </div>
      <div style={{position: 'absolute', top: LEISTE, left: 0, width: FENSTER.w, height: BILD_H, overflow: 'hidden'}}>
        <Img src={staticFile(bild)} style={bildStil} />
        {ueberblende && <Img src={staticFile(ueberblende.bild)} style={{...bildStil, opacity: ueber}} />}
        {markierungen?.map((mk, i) => {
          const p = aufFenster(kamera, mk.r);
          const s = spring({frame: f - mk.ab, fps, config: {damping: 14, stiffness: 120}});
          const farbe = mk.farbe ?? C.gruen;
          return (
            <div
              key={i}
              style={{
                position: 'absolute',
                left: p.left - 10,
                top: p.top - 8,
                width: p.width + 20,
                height: p.height + 16,
                borderRadius: 12,
                border: `3px solid ${farbe}`,
                boxShadow: `0 0 28px ${farbe}88, inset 0 0 18px ${farbe}33`,
                opacity: Math.min(1, s),
                transform: `scale(${1.15 - 0.15 * s})`,
              }}
            />
          );
        })}
      </div>
    </div>
  );
};

// ── Szene 1: Intro ──────────────────────────────────────────────────────────
const Intro: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const blende = useBlende(S.intro[1]);
  const logo = spring({frame: f - 6, fps, config: {damping: 12, stiffness: 90}});
  const t1 = spring({frame: f - 22, fps, config: {damping: 200}});
  const t2 = spring({frame: f - 40, fps, config: {damping: 200}});
  return (
    <AbsoluteFill style={{opacity: blende, alignItems: 'center', justifyContent: 'center', fontFamily: SCHRIFT}}>
      <Img
        src={staticFile('logo.png')}
        style={{
          width: 220,
          height: 220,
          transform: `scale(${logo}) rotate(${(1 - logo) * -12}deg)`,
          filter: 'drop-shadow(0 18px 40px rgba(90,160,230,0.45))',
        }}
      />
      <div
        style={{
          marginTop: 34,
          fontSize: 84,
          fontWeight: 800,
          color: C.text,
          letterSpacing: -1.5,
          opacity: t1,
          transform: `translateY(${(1 - t1) * 30}px)`,
        }}
      >
        Was spart mein <span style={{color: C.gruen}}>E-Auto</span> wirklich?
      </div>
      <div
        style={{
          marginTop: 14,
          fontSize: 34,
          color: C.leise,
          opacity: t2,
          transform: `translateY(${(1 - t2) * 20}px)`,
        }}
      >
        EV Tracker – das Home-Assistant-Add-on für dein Elektroauto
      </div>
    </AbsoluteFill>
  );
};

// ── Szene 2: Dashboard ──────────────────────────────────────────────────────
const Dashboard: React.FC = () => {
  const f = useCurrentFrame();
  const blende = useBlende(S.dashboard[1]);
  const kamera = kameraBei(f, [
    [0, {x: 0, y: 0, w: 1280}],
    [70, {x: 0, y: 0, w: 1280}],
    [140, {x: 0, y: 40, w: 860}],
    [190, {x: 0, y: 40, w: 860}],
    [250, {x: 0, y: 0, w: 1280}],
  ]);
  const zweiterText = f > 185;
  return (
    <AbsoluteFill style={{opacity: blende}}>
      <Sequence durationInFrames={185} layout="none">
        <Titel zeile="Deine Ersparnis – automatisch berechnet" unter="Strom gegen Benzin, dazu KFZ-Steuer und THG-Quote" />
      </Sequence>
      {zweiterText && (
        <Sequence from={185} layout="none">
          <Titel zeile="Für jeden Zeitraum" unter="Jahr, Quartal, Sommer oder Winter – ein Klick" />
        </Sequence>
      )}
      <Aufnahme
        bild="dashboard.png"
        url="homeassistant.local:8123/ev-tracker"
        kamera={kamera}
        ueberblende={{bild: 'dashboard_sommer.png', ab: 205, dauer: 18}}
        markierungen={f >= 110 && f < 195 ? [{r: {x: 34, y: 116, w: 132, h: 40}, ab: 120}] : []}
      />
    </AbsoluteFill>
  );
};

// ── Szene 3: Amortisation ───────────────────────────────────────────────────
const Amortisation: React.FC = () => {
  const f = useCurrentFrame();
  const blende = useBlende(S.amortisation[1]);
  const kamera = kameraBei(f, [
    [0, {x: 0, y: 150, w: 1280}],
    [60, {x: 0, y: 300, w: 1280}],
    [130, {x: 0, y: 300, w: 1280}],
    [200, {x: 10, y: 325, w: 760}],
    [300, {x: 10, y: 325, w: 760}],
  ]);
  return (
    <AbsoluteFill style={{opacity: blende}}>
      <Titel zeile="Wann hat sich der Mehrpreis bezahlt gemacht?" unter="Kaufpreis eintragen – die App rechnet Monat für Monat mit" farbe={C.orange} />
      <Aufnahme
        bild="dashboard.png"
        url="homeassistant.local:8123/ev-tracker"
        kamera={kamera}
        markierungen={f > 205 ? [{r: {x: 33, y: 372, w: 285, h: 28}, ab: 215, farbe: C.orange}] : []}
      />
    </AbsoluteFill>
  );
};

// ── Szene 4: Diagramme ──────────────────────────────────────────────────────
const Diagramme: React.FC = () => {
  const f = useCurrentFrame();
  const blende = useBlende(S.diagramme[1]);
  const kamera = kameraBei(f, [
    [0, {x: 0, y: 830, w: 1280}],
    [90, {x: 0, y: 830, w: 1280}],
    [170, {x: 0, y: 1200, w: 1280}],
    [215, {x: 0, y: 1200, w: 1280}],
    [290, {x: 0, y: 1935, w: 1280}],
  ]);
  const texte: [number, string, string][] = [
    [0, 'Kosten & Ersparnis jeden Monat', 'Was der Benziner gekostet hätte – und was du wirklich zahlst'],
    [130, 'Verbrauch im Sommer und Winter', 'Laut Ladung und laut Akkustand, dazu das gesparte CO2'],
    [235, 'Woher dein Strom kommt', 'PV, Wallbox, öffentliches Laden – nach Kosten und kWh'],
  ];
  const aktiv = [...texte].reverse().find((t) => f >= t[0])!;
  return (
    <AbsoluteFill style={{opacity: blende}}>
      <Sequence key={aktiv[0]} from={aktiv[0]} layout="none">
        <Titel zeile={aktiv[1]} unter={aktiv[2]} farbe={C.gruen} />
      </Sequence>
      <Aufnahme bild="dashboard.png" url="homeassistant.local:8123/ev-tracker" kamera={kamera} />
    </AbsoluteFill>
  );
};

// ── Szene 5: Lade-Abo ───────────────────────────────────────────────────────
const Abo: React.FC = () => {
  const f = useCurrentFrame();
  const blende = useBlende(S.abo[1]);
  const kamera = kameraBei(f, [
    [0, {x: 0, y: 1500, w: 1280}],
    [70, {x: 0, y: 1745, w: 1280}],
    [140, {x: 0, y: 1745, w: 1280}],
    [210, {x: 8, y: 1750, w: 820}],
    [300, {x: 8, y: 1750, w: 820}],
  ]);
  return (
    <AbsoluteFill style={{opacity: blende}}>
      <Titel zeile="Lohnt sich dein Lade-Abo?" unter="Break-even, Ersparnis je Monat und der Vergleich mit Ad-hoc-Preisen" farbe={C.blau} />
      <Aufnahme
        bild="ladetarife.png"
        url="homeassistant.local:8123/ev-tracker/ladetarife"
        kamera={kamera}
        markierungen={f > 205 ? [{r: {x: 30, y: 1806, w: 548, h: 28}, ab: 215, farbe: C.gruen}] : []}
      />
    </AbsoluteFill>
  );
};

// ── Szene 6: Home Assistant und Monatsbericht ──────────────────────────────
const HomeAssistant: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const blende = useBlende(S.ha[1]);
  const punkte = [
    ['🚗', 'Kilometer und Akkustand direkt vom Auto'],
    ['☀️', 'PV-Strom und Wallbox aus Home Assistant'],
    ['⛽', 'Benzinpreise für den Vergleich'],
    ['✉️', 'Monatsbericht per Mail'],
    ['🚙', 'Ein oder mehrere E-Autos'],
  ];
  const bericht = spring({frame: f - 10, fps, config: {damping: 200}});
  // langsamer Zoom auf den Bericht
  const zoom = interpolate(f, [0, S.ha[1]], [1, 1.04]);
  return (
    <AbsoluteFill style={{opacity: blende, fontFamily: SCHRIFT}}>
      <Titel zeile="Läuft von selbst – direkt in Home Assistant" unter="Einmal einrichten, danach kommen die Daten automatisch" />
      <div style={{position: 'absolute', left: 230, top: 250}}>
        {punkte.map(([icon, text], i) => {
          const s = spring({frame: f - 20 - i * 14, fps, config: {damping: 200}});
          return (
            <div
              key={text}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 22,
                marginBottom: 30,
                opacity: s,
                transform: `translateX(${(1 - s) * -40}px)`,
              }}
            >
              <div
                style={{
                  width: 72,
                  height: 72,
                  borderRadius: 18,
                  background: C.karte,
                  border: `1px solid ${C.rand}`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 36,
                }}
              >
                {icon}
              </div>
              <div style={{fontSize: 38, color: C.text, fontWeight: 600}}>{text}</div>
            </div>
          );
        })}
      </div>
      <div
        style={{
          position: 'absolute',
          left: 1130,
          top: 175,
          width: 600,
          height: 874,
          borderRadius: 14,
          overflow: 'hidden',
          boxShadow: '0 30px 80px rgba(0,0,0,0.55)',
          opacity: bericht,
          transform: `translateY(${(1 - bericht) * 60}px) rotate(${(1 - bericht) * 3}deg) scale(${zoom})`,
          background: '#f3f5f8',
        }}
      >
        <Img
          src={staticFile('bericht.png')}
          style={{width: 600}}
        />
      </div>
    </AbsoluteFill>
  );
};

// ── Szene 7: Abspann ────────────────────────────────────────────────────────
const Outro: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const blende = interpolate(f, [0, 14], [0, 1], {extrapolateRight: 'clamp'});
  const logo = spring({frame: f - 4, fps, config: {damping: 12, stiffness: 90}});
  const t = (v: number) => spring({frame: f - v, fps, config: {damping: 200}});
  const ende = interpolate(f, [S.outro[1] - 30, S.outro[1]], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const zeile = (v: number): React.CSSProperties => ({opacity: t(v), transform: `translateY(${(1 - t(v)) * 20}px)`});
  return (
    <AbsoluteFill style={{opacity: blende * ende, alignItems: 'center', justifyContent: 'center', fontFamily: SCHRIFT}}>
      <Img src={staticFile('logo.png')} style={{width: 180, height: 180, transform: `scale(${logo})`}} />
      <div style={{marginTop: 26, fontSize: 76, fontWeight: 800, color: C.text, letterSpacing: -1, ...zeile(16)}}>
        EV Tracker
      </div>
      <div style={{marginTop: 8, fontSize: 40, color: C.gruen, fontWeight: 600, ...zeile(28)}}>
        Kostenlos &amp; Open Source
      </div>
      <div style={{marginTop: 10, fontSize: 30, color: C.leise, ...zeile(38)}}>
        Add-on für Home Assistant · Deutsch &amp; Englisch
      </div>
      <div
        style={{
          marginTop: 44,
          fontSize: 34,
          color: C.text,
          padding: '16px 34px',
          borderRadius: 14,
          background: C.karte,
          border: `1px solid ${C.rand}`,
          ...zeile(52),
        }}
      >
        github.com/HasenbeinMH/ev-tracker-ha
      </div>
    </AbsoluteFill>
  );
};

// ── Gesamtes Video ──────────────────────────────────────────────────────────
export const Werbevideo: React.FC = () => (
  <AbsoluteFill style={{backgroundColor: C.bg}}>
    <Hintergrund />
    <Sequence from={S.intro[0]} durationInFrames={S.intro[1]}>
      <Intro />
    </Sequence>
    <Sequence from={S.dashboard[0]} durationInFrames={S.dashboard[1]}>
      <Dashboard />
    </Sequence>
    <Sequence from={S.amortisation[0]} durationInFrames={S.amortisation[1]}>
      <Amortisation />
    </Sequence>
    <Sequence from={S.diagramme[0]} durationInFrames={S.diagramme[1]}>
      <Diagramme />
    </Sequence>
    <Sequence from={S.abo[0]} durationInFrames={S.abo[1]}>
      <Abo />
    </Sequence>
    <Sequence from={S.ha[0]} durationInFrames={S.ha[1]}>
      <HomeAssistant />
    </Sequence>
    <Sequence from={S.outro[0]} durationInFrames={S.outro[1]}>
      <Outro />
    </Sequence>
    <Audio src={staticFile('musik.wav')} />
  </AbsoluteFill>
);
