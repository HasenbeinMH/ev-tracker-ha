"""Hintergrundmusik fuer das Video, komplett synthetisiert (keine Samples, keine fremden Rechte).

60 s, 96 BPM, Akkorde Am – F – C – G. Intro nur Flaechen, dann Arpeggio und leichter Puls,
am Ende ausklingen.
"""
import os, wave
import numpy as np

SR = 48000
DAUER = 60.0
BPM = 96
SCHLAG = 60 / BPM
TAKT = 4 * SCHLAG
N = int(SR * DAUER)
t_all = np.arange(N) / SR
rng = np.random.default_rng(5)


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def tiefpass(x, cutoff):
    """Einfacher Tiefpass erster Ordnung."""
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):          # bewusst schlicht; ~3 Mio. Schritte je Spur
        acc = (1 - a) * x[i] + a * acc
        y[i] = acc
    return y


def tiefpass_schnell(x, cutoff):
    from scipy.signal import lfilter  # falls vorhanden
    a = np.exp(-2 * np.pi * cutoff / SR)
    return lfilter([1 - a], [1, -a], x)


try:
    import scipy  # noqa
    tp = tiefpass_schnell
except ImportError:
    tp = tiefpass

# Akkorde (MIDI): Am, F, C, G – je ein Takt
AKKORDE = [[57, 60, 64], [53, 57, 60], [48, 55, 60, 64], [55, 59, 62]]
BASS = [45, 41, 48, 43]

links = np.zeros(N)
rechts = np.zeros(N)


def hinzu(sig, start, pan=0.0, gain=1.0):
    i0 = int(start * SR)
    if i0 >= N:
        return
    sig = sig[: N - i0] * gain
    links[i0:i0 + len(sig)] += sig * np.sqrt(0.5 * (1 - pan))
    rechts[i0:i0 + len(sig)] += sig * np.sqrt(0.5 * (1 + pan))


def huellkurve(n, attack, release):
    e = np.ones(n)
    a, r = int(attack * SR), int(release * SR)
    e[:a] = np.linspace(0, 1, a)
    e[-r:] *= np.linspace(1, 0, r)
    return e


# Flaechen: verstimmte Saegezahn-Stimmen, weich gefiltert, Akkord ueberlappt in den naechsten
takte = int(np.ceil(DAUER / TAKT))
for k in range(takte):
    start = k * TAKT
    akkord = AKKORDE[k % 4]
    laenge = TAKT * 1.35
    n = int(laenge * SR)
    t = np.arange(n) / SR
    pad = np.zeros(n)
    for note in akkord:
        for verstimmung in (-0.07, 0.0, 0.08):
            f = hz(note + 12) * 2 ** (verstimmung / 12)
            phase = rng.uniform(0, 1)
            pad += 2 * ((t * f + phase) % 1) - 1
    pad = tp(pad, 1400) * huellkurve(n, 0.9, 1.2) / (len(akkord) * 3)
    hinzu(pad, start, pan=-0.15, gain=0.30)
    hinzu(pad, start, pan=0.15, gain=0.30)

    # Bass: Sinus mit etwas Oberton
    nb = int(TAKT * SR)
    tb = np.arange(nb) / SR
    fb = hz(BASS[k % 4])
    bass = (np.sin(2 * np.pi * fb * tb) + 0.25 * np.sin(4 * np.pi * fb * tb)) * huellkurve(nb, 0.05, 0.4)
    if start >= 4.5:
        hinzu(bass, start, gain=0.22)

# Arpeggio ab 5 s: Achtel, Glocken-Sinus mit Ausklang, Ping-Pong im Stereobild
achtel = SCHLAG / 2
muster = [0, 1, 2, 1, 2, 0, 1, 2]
i = 0
zeit = 5.0
while zeit < 53.5:
    takt = int(zeit // TAKT)
    akkord = AKKORDE[takt % 4]
    note = akkord[muster[i % 8] % len(akkord)] + 24
    n = int(0.9 * SR)
    t = np.arange(n) / SR
    f = hz(note)
    ton = (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 9)) * np.exp(-t * 5.5)
    ton *= np.minimum(1, t / 0.004)
    hinzu(ton, zeit, pan=0.45 if i % 2 else -0.45, gain=0.075)
    i += 1
    zeit += achtel

# Puls ab 15 s: weicher Kick auf 1 und 3, leise Hi-Hat auf den Offbeats
schlag = 15.0
while schlag < 52.5:
    nk = int(0.35 * SR)
    tk = np.arange(nk) / SR
    kick = np.sin(2 * np.pi * (45 + 70 * np.exp(-tk * 30)) * tk) * np.exp(-tk * 9)
    hinzu(kick, schlag, gain=0.30)
    nh = int(0.06 * SR)
    hat = tp(rng.normal(0, 1, nh), 9000)
    hat = (rng.normal(0, 1, nh) - hat) * np.exp(-np.arange(nh) / SR * 70)
    hinzu(hat, schlag + SCHLAG, pan=0.3, gain=0.035)
    hinzu(hat, schlag + SCHLAG * 2.5, pan=-0.3, gain=0.025)
    schlag += 2 * SCHLAG

# Raum: zwei Rueckkopplungs-Echos, leicht gefiltert
def echo(x, verz, fb, mix):
    d = int(verz * SR)
    y = x.copy()
    for k in range(d, len(y), d):
        y[k:k + d] += y[k - d:k][: len(y[k:k + d])] * fb
    return x + (tp(y - x, 3500)) * mix

links = echo(links, SCHLAG * 0.75, 0.35, 0.5)
rechts = echo(rechts, SCHLAG * 0.5, 0.35, 0.5)

# Ein-/Ausblenden und Normalisieren
gesamt = np.ones(N)
ein = int(2.5 * SR)
aus = int(6.0 * SR)
gesamt[:ein] = np.linspace(0, 1, ein) ** 2
gesamt[-aus:] = np.linspace(1, 0, aus) ** 1.5
links *= gesamt
rechts *= gesamt
spitze = max(np.abs(links).max(), np.abs(rechts).max())
links = np.tanh(links / spitze * 1.1) * 0.8
rechts = np.tanh(rechts / spitze * 1.1) * 0.8

ziel = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "musik.wav")
os.makedirs(os.path.dirname(ziel), exist_ok=True)
daten = (np.stack([links, rechts], axis=1) * 32767).astype("<i2")
with wave.open(ziel, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(daten.tobytes())
print("geschrieben:", ziel, f"{DAUER:.0f} s")
