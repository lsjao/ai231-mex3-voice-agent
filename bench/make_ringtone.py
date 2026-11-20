"""Generate the Kuya Jukebox ready-jingle: a bright rising arpeggio with a bell-like tone (fundamental + harmonics,
fast attack, exponential decay). Louder than the old beep (peak ~0.95 of full scale vs 0.4).
Usage: python bench/make_ringtone.py [out.wav]   (default: ringtone.wav, 24 kHz mono PCM16)"""
import sys
import wave

import numpy as np

RATE = 24000
# C5 E5 G5 C6 then a held G5+C6 "ding": (frequency Hz, start s, length s)
NOTES = [(523.25, 0.00, 0.18), (659.25, 0.14, 0.18), (783.99, 0.28, 0.18), (1046.50, 0.42, 0.55),
         (783.99, 0.42, 0.55)]


def bell(freq: float, length: float) -> np.ndarray:
    t = np.arange(int(RATE * length)) / RATE
    tone = (np.sin(2 * np.pi * freq * t) + 0.45 * np.sin(2 * np.pi * 2 * freq * t)
            + 0.2 * np.sin(2 * np.pi * 3.01 * freq * t))
    attack = np.minimum(1.0, t / 0.006)             # 6 ms attack: no click
    decay = np.exp(-t * (5.0 if length < 0.3 else 3.2))
    return tone * attack * decay


total = max(start + length for _, start, length in NOTES) + 0.1
mix = np.zeros(int(RATE * total))
for freq, start, length in NOTES:
    s = int(RATE * start)
    voice = bell(freq, length)
    mix[s:s + len(voice)] += voice
mix = mix / np.abs(mix).max() * 0.95
out = sys.argv[1] if len(sys.argv) > 1 else "ringtone.wav"
with wave.open(out, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(RATE)
    w.writeframes((mix * 32767).astype(np.int16).tobytes())
print(f"wrote {out}: {total:.2f}s, peak {np.abs(mix).max():.2f}")
