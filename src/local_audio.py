"""Local mic/speaker transport for the Pi built on sounddevice (PortAudio), adapted from Pipecat's pyaudio-based
LocalAudioTransport (pyaudio needs system headers we can't install without sudo).

The USB mic only opens at 48 kHz natively, so we capture at 48 kHz and downsample to 16 kHz with Pipecat's streaming
sinc resampler. The speaker is the 3.5 mm Headphones card.
"""
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

import sounddevice as sd

from pipecat.audio.resamplers.sinc_stream_resampler import SincStreamAudioResampler
from pipecat.frames.frames import InputAudioRawFrame, OutputAudioRawFrame, StartFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameProcessorSetup
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import BaseTransport, TransportParams

MIC_RATE = 48000


def find_device(name_part: str, want_input: bool) -> int:
    key = "max_input_channels" if want_input else "max_output_channels"
    for i, d in enumerate(sd.query_devices()):
        if name_part.lower() in d["name"].lower() and d[key] > 0:
            return i
    raise RuntimeError(f"no {'input' if want_input else 'output'} audio device matching {name_part!r}: "
                       f"{[d['name'] for d in sd.query_devices()]}")


class _In(BaseInputTransport):
    def __init__(self, params: TransportParams, device: int):
        super().__init__(params)
        self._device = device
        self._stream = None
        self._rs = SincStreamAudioResampler()
        self._out_rate = 16000

    async def start(self, frame: StartFrame):
        await super().start(frame)
        self._out_rate = self._params.audio_in_sample_rate or 16000
        loop = self.get_event_loop()

        def cb(indata, frames, time_info, status):
            asyncio.run_coroutine_threadsafe(self._on_audio(bytes(indata)), loop)

        self._stream = sd.RawInputStream(samplerate=MIC_RATE, channels=1, dtype="int16",
                                         blocksize=MIC_RATE // 50, device=self._device, callback=cb)  # 20 ms
        self._stream.start()
        await self.set_transport_ready(frame)

    async def _on_audio(self, raw48: bytes):
        pcm = await self._rs.resample(raw48, MIC_RATE, self._out_rate)
        if pcm:
            await self.push_audio_frame(InputAudioRawFrame(audio=pcm, sample_rate=self._out_rate, num_channels=1))

    async def cleanup(self):
        await super().cleanup()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class _Out(BaseOutputTransport):
    def __init__(self, params: TransportParams, device: int):
        super().__init__(params)
        self._device = device
        self._stream = None
        self._executor = ThreadPoolExecutor(max_workers=1)

    async def start(self, frame: StartFrame):
        await super().start(frame)
        self._stream = sd.RawOutputStream(samplerate=self.sample_rate, channels=1, dtype="int16",
                                          device=self._device, latency="low")
        self._stream.start()
        await self.set_transport_ready(frame)

    async def write_audio_frame(self, frame: OutputAudioRawFrame) -> bool:
        if self._stream is None:
            return False
        await self.get_event_loop().run_in_executor(self._executor, self._stream.write, frame.audio)
        return True

    async def cleanup(self):
        try:
            await super().cleanup()
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
                self._stream = None
        finally:
            self._executor.shutdown(wait=False)


class SdAudioTransport(BaseTransport):
    def __init__(self, params: TransportParams, mic: str | None = None, speaker: str | None = None):
        super().__init__()
        self._params = params
        self._mic = find_device(mic or os.environ.get("MIC_DEVICE", "USB"), True)
        self._spk = find_device(speaker or os.environ.get("SPEAKER_DEVICE", "Headphones"), False)
        self._input = None
        self._output = None

    def input(self) -> FrameProcessor:
        if not self._input:
            self._input = _In(self._params, self._mic)
        return self._input

    def output(self) -> FrameProcessor:
        if not self._output:
            self._output = _Out(self._params, self._spk)
        return self._output
