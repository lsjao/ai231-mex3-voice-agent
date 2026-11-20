"""Phase 0: run Silero VAD (via pipecat's bundled model) over a 16 kHz mono wav; print speech segments."""
import asyncio, inspect, sys, wave
import numpy as np
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADState

path = sys.argv[1] if len(sys.argv) > 1 else "test.wav"
w = wave.open(path)
assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2
pcm = w.readframes(w.getnframes())
vad = SileroVADAnalyzer(sample_rate=16000)
vad.set_sample_rate(16000)  # a pipeline transport normally does this
step = vad.num_frames_required() * 2  # bytes per analysis window
async def main():
    global segs
    segs, start, speaking = [], None, False
    for i in range(0, len(pcm) - step + 1, step):
        t = i / 2 / 16000
        s = vad.analyze_audio(pcm[i:i + step])
        if inspect.isawaitable(s):  # async in newer Pipecat
            s = await s
        if s == VADState.SPEAKING and not speaking:
            start, speaking = t, True
        elif s == VADState.QUIET and speaking:
            segs.append((start, t)); speaking = False
    if speaking:
        segs.append((start, len(pcm) / 2 / 16000))

    return segs

segs = asyncio.run(main())
a = np.frombuffer(pcm, np.int16)
print(f"peak={np.abs(a).max()} rms={np.sqrt((a.astype(float)**2).mean()):.0f}")
for s, e in segs:
    print(f"speech {s:.2f}s -> {e:.2f}s")
print(f"segments={len(segs)} speech_total={sum(e - s for s, e in segs):.2f}s of {len(a)/16000:.2f}s")
