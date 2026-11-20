"""Pipecat STT and TTS services that talk to OUR MCP servers (asr-mcp, tts-mcp) instead of a vendor SDK.

They emit only standard Pipecat frames (TranscriptionFrame, TTSStarted/Audio/Stopped), because the class benchmark
reads stage timings from those frames.
"""
import asyncio
import base64
import collections
import json
from collections.abc import AsyncGenerator

from loguru import logger

from pipecat.frames.frames import Frame, TranscriptionFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601

from src.mcp_conn import McpConn

ASR_URL = "http://127.0.0.1:8101/mcp"
TTS_URL = "http://127.0.0.1:8102/mcp"


class McpSTT(STTService):
    """Streams speech to asr-mcp between VAD start and VAD stop, then asks it for the final transcript.

    Audio is only forwarded while the user is speaking (plus a short pre-roll so the first syllable isn't clipped),
    which keeps Deepgram usage and bandwidth low.
    """

    def __init__(self, *, url: str = ASR_URL, chunk_ms: int = 100, preroll_ms: int = 900, **kwargs):
        super().__init__(sample_rate=16000, ttfs_p99_latency=1.0,
                         settings=STTSettings(model=None, language=None), **kwargs)
        self._conn = McpConn(url)
        self._chunk_bytes = 16000 * 2 * chunk_ms // 1000
        self._preroll = collections.deque()
        self._preroll_max = 16000 * 2 * preroll_ms // 1000
        self._preroll_len = 0
        self._buf = bytearray()
        self._active = False
        self._lock = asyncio.Lock()  # serialises start/push/finish for one utterance at a time

    def can_generate_metrics(self) -> bool:
        return False

    async def start(self, frame):
        await super().start(frame)
        await self._conn.start()
        await self._conn.call("asr_start")  # opens the warm Deepgram socket before the first word

    async def cleanup(self):
        await super().cleanup()
        await self._conn.close()

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        if self._active:
            self._buf += audio
            if len(self._buf) >= self._chunk_bytes:
                chunk, self._buf = bytes(self._buf), bytearray()
                await self._push(chunk)
        else:
            self._preroll.append(audio)
            self._preroll_len += len(audio)
            while self._preroll_len > self._preroll_max and len(self._preroll) > 1:
                self._preroll_len -= len(self._preroll.popleft())
        return
        yield  # makes this an async generator; transcripts are pushed from _finish()

    async def _push(self, chunk: bytes):
        try:
            await self._conn.call("asr_push", {"audio_b64": base64.b64encode(chunk).decode()})
        except Exception as e:
            logger.warning(f"asr_push failed: {e}")

    async def _handle_vad_user_started_speaking(self, frame: VADUserStartedSpeakingFrame):
        await super()._handle_vad_user_started_speaking(frame)
        logger.info("[stt] VAD: user started speaking")
        async with self._lock:
            try:
                await self._conn.call("asr_start")
            except Exception as e:
                logger.warning(f"asr_start failed: {e}")
            pre = b"".join(self._preroll)
            self._preroll.clear()
            self._preroll_len = 0
            self._buf = bytearray()
            self._active = True
            if pre:
                await self._push(pre)

    async def _handle_vad_user_stopped_speaking(self, frame: VADUserStoppedSpeakingFrame):
        await super()._handle_vad_user_stopped_speaking(frame)
        logger.info("[stt] VAD: user stopped speaking")
        self._active = False
        tail, self._buf = bytes(self._buf), bytearray()
        # Don't block the frame flow (benchmark marks VAD end from this frame): finish in the background.
        self.create_task(self._finish(tail), name="asr_finish")

    async def _finish(self, tail: bytes):
        async with self._lock:
            if tail:
                await self._push(tail)
            try:
                text = (await self._conn.call("asr_finish")).strip()
            except Exception as e:
                logger.error(f"asr_finish failed: {e}")
                return
        logger.info(f"[stt] final transcript: {text!r}")
        if text:
            await self.push_frame(
                TranscriptionFrame(text, "", time_now_iso8601(), Language.EN, finalized=True)
            )


class McpTTS(TTSService):
    """Speaks through tts-mcp: speak_start returns the first audio chunk fast, speak_next the rest."""

    def __init__(self, *, url: str = TTS_URL, sample_rate: int = 24000, **kwargs):
        super().__init__(sample_rate=sample_rate, push_start_frame=True, push_stop_frames=True,
                         settings=TTSSettings(model=None, voice=None, language=None), **kwargs)
        self._conn = McpConn(url)

    def can_generate_metrics(self) -> bool:
        return False

    async def start(self, frame):
        await super().start(frame)
        await self._conn.start()

    async def cleanup(self):
        await super().cleanup()
        await self._conn.close()

    async def _chunks(self, text: str):
        r = json.loads(await self._conn.call("speak_start", {"text": text}))
        job = r.get("id")
        while True:
            if r["audio"]:
                yield base64.b64decode(r["audio"])
            if r["done"]:
                return
            r = json.loads(await self._conn.call("speak_next", {"job_id": job}))

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        try:
            async for frame in self._stream_audio_frames_from_iterator(
                self._chunks(text), in_sample_rate=24000, context_id=context_id
            ):
                yield frame
        except asyncio.CancelledError:
            await self._conn.call("speak_cancel")  # barge-in: stop Deepgram synthesizing what nobody will hear
            raise

    async def on_interruption(self):  # called by the pipeline on barge-in in some Pipecat versions
        try:
            await self._conn.call("speak_cancel")
        except Exception:
            pass
