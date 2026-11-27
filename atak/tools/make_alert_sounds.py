"""The CrowdCAD ATAK plugin's assignment-alert sounds, and the candidates they were picked from.

    python atak/tools/make_alert_sounds.py             # writes the two shipped sounds to res/raw
    python atak/tools/make_alert_sounds.py --all DIR   # all seven candidates (as auditioned) to DIR

Each is a short WAV (mono, 16-bit, 24 kHz) that AssignmentAlarm loops on the ALARM stream until
Acknowledge (or 5 s). Pure stdlib, so the file Jon auditioned is byte-for-byte the file that ships.
Shipped (Jon, 2026-11-26): 5 soft pulses (default) and 7 hi-lo (dispatcher's choice, CloudTAK
Settings → bridge alert_sound → roster CoT alert="soft|hilo").
"""
import math, os, struct, sys, wave

SR = 24000
ALL = "--all" in sys.argv
_args = [a for a in sys.argv[1:] if a != "--all"]
OUT = _args[0] if _args else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "src", "main", "res", "raw")
SHIPPED = {"5-soft-pulses": "alert_soft_pulses", "7-hi-lo": "alert_hi_lo"}   # candidate → res/raw name


def silence(sec):
    return [0.0] * int(SR * sec)


def note(freq, sec, decay=None, partials=((1, 1.0),), attack=0.006, release=0.03):
    """A tone with a soft attack; `decay` (s) gives a bell/marimba fade, else a flat sustain."""
    n = int(SR * sec)
    out = []
    for i in range(n):
        t = i / SR
        v = sum(a * math.sin(2 * math.pi * freq * m * t) * (math.exp(-t * m / decay) if decay else 1)
                for m, a in partials)
        env = min(1.0, t / attack) * min(1.0, (sec - t) / release)
        out.append(v * env)
    return out


def mix_at(track, start, clip):
    i0 = int(start * SR)
    need = i0 + len(clip)
    if len(track) < need:
        track.extend([0.0] * (need - len(track)))
    for i, v in enumerate(clip):
        track[i0 + i] += v
    return track


def write(name, samples, peak_db=-3.0):
    if not ALL:
        if name not in SHIPPED:
            return
        name = SHIPPED[name]
    peak = max(abs(s) for s in samples) or 1
    gain = 10 ** (peak_db / 20) / peak
    path = os.path.join(OUT, name + ".wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s * gain)) * 32767)) for s in samples))
    print(path, round(len(samples) / SR, 2), "s")


BELL = ((1, 1.0), (2.0, 0.35), (3.01, 0.12))
MARIMBA = ((1, 1.0), (3.9, 0.25))
os.makedirs(OUT, exist_ok=True)

# 1 Ding-dong: two bell notes, like a front-desk door chime but brighter.
t = []
mix_at(t, 0.00, note(1318.5, 0.9, decay=0.45, partials=BELL))
mix_at(t, 0.32, note(1046.5, 1.1, decay=0.55, partials=BELL))
write("1-ding-dong", t + silence(0.25))

# 2 Rising triad: three quick bell notes up, a "new message for you" feel.
t = []
for k, f in enumerate((1046.5, 1318.5, 1568.0)):
    mix_at(t, k * 0.14, note(f, 0.6, decay=0.28, partials=BELL))
write("2-rising-triad", t + silence(0.45))

# 3 Two-tone pager: a long high tone then a long low tone, like a fire/EMS radio page.
t = note(1100, 0.55, release=0.04) + note(820, 0.85, release=0.08)
write("3-two-tone-pager", t + silence(0.35))

# 4 Marimba run: four wooden notes up an A-minor arpeggio.
t = []
for k, f in enumerate((880.0, 1046.5, 1318.5, 1760.0)):
    mix_at(t, k * 0.1, note(f, 0.5, decay=0.18, partials=MARIMBA))
write("4-marimba-run", t + silence(0.55))

# 5 Soft pulses: three round 880 Hz pulses (the current beep idea, minus the harsh edge).
t = []
for k in range(3):
    mix_at(t, k * 0.26, note(880, 0.17, attack=0.025, release=0.06))
write("5-soft-pulses", t + silence(0.55))

# 6 Descending chime: three bell notes down, calmer.
t = []
for k, f in enumerate((1568.0, 1318.5, 1046.5)):
    mix_at(t, k * 0.2, note(f, 0.8, decay=0.4, partials=BELL))
write("6-descending-chime", t + silence(0.3))

# 7 Hi-lo: alternating 960 / 770 Hz, urgent but rounded (sine, soft edges).
t = []
for k in range(4):
    t += note(960, 0.22, attack=0.015, release=0.03) + note(770, 0.22, attack=0.015, release=0.03)
write("7-hi-lo", t + silence(0.3))
