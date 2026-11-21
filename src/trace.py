"""TraceObserver: logs each conversational turn with timings (what was heard, what the LLM said, how long each stage took,
all on one monotonic clock) and writes the same REAL events to the session log that feeds the live visual (src/events.py).
Reads standard Pipecat frames only; nothing is scripted or generated here."""
import re
import time

from loguru import logger

from pipecat.frames.frames import (BotStartedSpeakingFrame, BotStoppedSpeakingFrame, FunctionCallInProgressFrame,
                                   FunctionCallResultFrame, InterruptionFrame, LLMFullResponseEndFrame,
                                   LLMFullResponseStartFrame, LLMTextFrame, TranscriptionFrame, TTSAudioRawFrame,
                                   TTSStartedFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)
from pipecat.observers.base_observer import BaseObserver, FramePushed

from src import events

MUSIC_ACTION = {"music_play": "play", "music_resume": "play", "music_next": "play", "music_previous": "play",
                "music_pause": "pause", "music_stop": "stop"}


def _ms(a, b):
    return None if a is None or b is None else max(0, int(round((a - b) * 1000)))


class TraceObserver(BaseObserver):
    def __init__(self):
        super().__init__()
        self._last: dict[str, float] = {}
        self._seen_ids: set[int] = set()
        self._t_vad_stop = None
        self._speaking = False
        self._reset_turn()

    def _reset_turn(self):
        self._t_final = self._first_text_t = self._t_first_sound = self._t_answer_audio = None
        self._t_tts_start = self._t_tts_audio = None
        self._llm_first = False
        self._text: list[str] = []
        self._tool_open, self._tool_ms, self._tool_t0 = False, 0.0, {}
        self._pending: str | None = None

    def _once(self, frame) -> bool:
        # Pipecat broadcasts some control frames as two copies with different ids: de-duplicate by type within
        # 50 ms. Streamed text tokens arrive faster than that, so those are de-duplicated by frame id instead.
        if isinstance(frame, LLMTextFrame):
            if frame.id in self._seen_ids:
                return False
            self._seen_ids.add(frame.id)
            return True
        key, now = type(frame).__name__, time.monotonic()
        if now - self._last.get(key, -1.0) < 0.05:
            return False
        self._last[key] = now
        return True

    @staticmethod
    def _since(t0) -> str:
        return "n/a" if t0 is None else f"{time.monotonic() - t0:.2f}s"

    # --- the agent's reply, emitted once its text is complete AND its first audio has started ------------------------
    def _emit_agent(self, partial: bool = False):
        text = self._pending if self._pending is not None else "".join(self._text).strip()
        if not text:
            return
        llm = _ms(self._first_text_t, self._t_final)
        if llm is not None:
            llm = max(0, llm - int(self._tool_ms * 1000))          # model time only: tool time is reported by tool events
        fields = {"text": text, "llm_ms": llm, "tts_ms": _ms(self._t_tts_audio, self._t_tts_start),
                  "e2e_ms": _ms(self._t_answer_audio, self._t_vad_stop),
                  "first_sound_ms": _ms(self._t_first_sound, self._t_vad_stop)}   # first_sound_ms: holding phrase or answer
        if partial:
            fields["partial"] = True
        events.emit("agent", **{k: v for k, v in fields.items() if v is not None})
        self._pending, self._text = None, []

    def _try_emit_agent(self):
        if self._pending is not None and self._t_answer_audio is not None:
            self._emit_agent()

    async def on_push_frame(self, data: FramePushed):
        f, now = data.frame, time.monotonic()
        if isinstance(f, TTSAudioRawFrame):                        # very frequent: only the first chunk matters
            if self._t_tts_audio is None and self._t_tts_start is not None:
                self._t_tts_audio = now
            return
        if isinstance(f, VADUserStartedSpeakingFrame) and self._once(f):
            logger.info("[trace] user speech start")
            events.emit("state", state="listening")
        elif isinstance(f, VADUserStoppedSpeakingFrame) and self._once(f):
            self._emit_agent(partial=bool(self._text))             # flush anything left over from the previous turn
            self._reset_turn()
            self._t_vad_stop, self._llm_first = now, True
            logger.info("[trace] user speech end (VAD)")
            events.emit("state", state="thinking")
        elif isinstance(f, TranscriptionFrame) and self._once(f):
            self._t_final = now
            logger.info(f"[trace] ASR final +{self._since(self._t_vad_stop)} after VAD end: {f.text!r}")
        elif isinstance(f, LLMFullResponseStartFrame) and self._once(f):
            self._text, self._first_text_t, self._t_tts_start, self._t_tts_audio = [], None, None, None
        elif isinstance(f, LLMTextFrame) and self._once(f):
            if self._llm_first:
                self._llm_first = False
                logger.info(f"[trace] LLM first token +{self._since(self._t_final)} after ASR final")
            if self._first_text_t is None:
                self._first_text_t = now
            self._text.append(f.text)
        elif isinstance(f, LLMFullResponseEndFrame) and self._once(f):
            text = "".join(self._text).strip()
            logger.info(f"[trace] bot said: {text!r}")
            if text:
                self._pending = text
                self._try_emit_agent()
        elif isinstance(f, TTSStartedFrame):
            if self._t_tts_start is None:
                self._t_tts_start = now
        elif isinstance(f, FunctionCallInProgressFrame) and f.tool_call_id not in self._tool_t0:   # one event per call id
            self._tool_open = True
            self._tool_t0[f.tool_call_id] = now
            events.emit("tool", name=f.function_name, phase="start")
            events.emit("state", state="tool")
        elif isinstance(f, FunctionCallResultFrame) and f.tool_call_id in self._tool_t0:           # ignore the extra copies
            ms = int(round((now - self._tool_t0.pop(f.tool_call_id)) * 1000))
            self._tool_ms += ms / 1000
            self._tool_open = False
            events.emit("tool", name=f.function_name, phase="end", ms=ms)
            action = MUSIC_ACTION.get(f.function_name)
            if action:
                m = re.match(r"^(?:Playing|Resuming) (.+?)\.?$", str(f.result or "").strip())
                events.emit("music", action=action, title=(m.group(1) if m else ""))
        elif isinstance(f, BotStartedSpeakingFrame) and self._once(f):
            logger.info(f"[trace] bot audio started: E2E {self._since(self._t_vad_stop)} after VAD end")
            if self._t_first_sound is None:
                self._t_first_sound = now
            if not self._tool_open and self._t_answer_audio is None:
                self._t_answer_audio = now                          # first audio after any tool finished = the answer
            self._speaking = True
            events.emit("state", state="speaking")
            self._try_emit_agent()
        elif isinstance(f, BotStoppedSpeakingFrame) and self._once(f):
            logger.info("[trace] bot audio stopped")
            self._speaking = False
            if self._pending is not None:
                self._emit_agent()                                  # reply text complete but no 'answer audio' mark
            if not self._tool_open:
                events.settle()
        elif isinstance(f, InterruptionFrame) and self._once(f):
            logger.info("[trace] INTERRUPTION (barge-in)")
            # Pipecat emits this frame at EVERY user speech start; it is only a real barge-in if the agent was talking
            # or mid-reply at that moment.
            if self._speaking or self._text or self._pending is not None or self._tool_open:
                events.emit("interrupt")
            self._emit_agent(partial=bool(self._text))
