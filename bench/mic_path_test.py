"""Isolate the live mic path: sounddevice capture at 48 kHz -> Pipecat sinc resampler -> 16 kHz -> Silero confidence.
Prints level and speech confidence per half second so we can see whether speech reaches the VAD.
Usage: python bench/mic_path_test.py [seconds]   (speak while it runs)"""
import asyncio
import sys
import time

import numpy as np
import sounddevice as sd

from pipecat.audio.resamplers.sinc_stream_resampler import SincStreamAudioResampler
from pipecat.audio.vad.silero import SileroVADAnalyzer

SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 8


def device(name):
    return next(i for i, d in enumerate(sd.query_devices()) if name in d["name"] and d["max_input_channels"] > 0)


async def main():
    vad = SileroVADAnalyzer(sample_rate=16000)
    vad.set_sample_rate(16000)
    rs = SincStreamAudioResampler()
    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    stream = sd.RawInputStream(samplerate=48000, channels=1, dtype="int16", blocksize=960, device=device("USB"),
                               callback=lambda d, f, t, s: loop.call_soon_threadsafe(q.put_nowait, bytes(d)))
    stream.start()
    t0, pcm16 = time.monotonic(), bytearray()
    while time.monotonic() - t0 < SECS:
        pcm16 += await rs.resample(await q.get(), 48000, 16000)
    stream.stop()
    stream.close()
    a = np.frombuffer(bytes(pcm16), np.int16)
    print(f"captured {len(a) / 16000:.1f}s at 16 kHz, peak={np.abs(a).max()} rms={np.sqrt((a.astype(float) ** 2).mean()):.0f}")
    win = 512
    best = 0.0
    # Run the REAL analyzer state machine (confidence AND loudness gate), as the agent does, with the agent's settings.
    from pipecat.audio.vad.vad_analyzer import VADParams, VADState
    real = SileroVADAnalyzer(sample_rate=16000, params=VADParams(confidence=0.8, start_secs=0.35, stop_secs=0.45))
    real.set_sample_rate(16000)
    ever_speaking, max_vol = False, 0.0
    for sec in range(int(len(a) / 16000 * 2)):
        seg = a[sec * 8000:(sec + 1) * 8000]
        confs, state, vol = [], None, 0.0
        for i in range(0, len(seg) - win + 1, win):
            chunk = seg[i:i + win].tobytes()
            confs.append(float(np.squeeze(vad.voice_confidence(chunk))))
            state = await real.analyze_audio(chunk)
            vol = max(vol, float(real._prev_volume))
        c = max(confs) if confs else 0.0
        best = max(best, c)
        max_vol = max(max_vol, vol)
        ever_speaking |= state == VADState.SPEAKING
        rms = float(np.sqrt((seg.astype(float) ** 2).mean())) if len(seg) else 0
        print(f"t={sec * 0.5:3.1f}s rms={rms:6.0f} conf={c:.2f} loudness={vol:.2f} state={state.name if state else '-'}")
    print(f"best confidence {best:.2f}; max loudness {max_vol:.2f} (gate 0.60); "
          f"REAL VAD TRIGGERED: {'YES (would interrupt)' if ever_speaking else 'no'}")

asyncio.run(main())
