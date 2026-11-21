"""ResumeObserver: pick an interrupted request back up, and report long-running work to the live visual.

When the user interrupts while a slow tool (search, page read, site build) is running, Pipecat cancels that call so the
interruption can be answered at once. Without this observer the cancelled request is simply lost. Here we remember it,
wait until the interruption has been dealt with (nobody speaking, the agent silent, no reply or tool in progress), and then
ask the agent to pick the original request up again, unless the person has since dropped it. Nothing here writes an answer:
the agent redoes the work with its own tools.

It also emits 'task' events (running / progress / done / cancelled / resumed) for the visual's progress indicator.
Reads standard Pipecat frames only."""
import asyncio
import time

from loguru import logger

from pipecat.frames.frames import (BotStartedSpeakingFrame, BotStoppedSpeakingFrame, FunctionCallCancelFrame,
                                   FunctionCallInProgressFrame, FunctionCallResultFrame, LLMFullResponseEndFrame,
                                   LLMFullResponseStartFrame, LLMMessagesAppendFrame, TranscriptionFrame,
                                   VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)
from pipecat.observers.base_observer import BaseObserver, FramePushed

from src import events

SLOW_TOOLS = {"web_search": "Searching the web", "read_page": "Reading a page", "publish_website": "Building your page", "create_public_repo": "Creating your repository"}
IDLE_SECS = 1.5          # the conversation must be quiet this long before an interrupted request is resumed
PROGRESS_SECS = 3.0      # heartbeat for the visual while a slow tool runs
RESUME_PROMPT = ('[automatic note] You were interrupted while working on this earlier request: "{req}". That work was cancelled '
                 'before it finished. The interruption has now been handled. Continue with the earlier request now: use your tools '
                 'again if needed and give the answer, unless the person has since asked it again, answered it, or said they no '
                 'longer want it. Do not mention this note.')


class ResumeObserver(BaseObserver):
    def __init__(self):
        super().__init__()
        self._worker = None
        self._last_user = ""
        self._active: dict[str, dict] = {}            # tool_call_id -> {name, request, t0, beat}
        self._pending: list[dict] = []                # cancelled slow requests waiting to be resumed
        self._user_speaking = self._bot_speaking = self._llm_busy = False
        self._last_activity = time.monotonic()
        self._last_transcript = 0.0
        self._watch_task = None
        self._seen: set[str] = set()

    def attach(self, worker):
        self._worker = worker

    def note_user(self, text: str):
        """For text-only tests: stands in for a TranscriptionFrame."""
        self._last_user = text.strip()

    def _touch(self):
        self._last_activity = time.monotonic()

    def _once(self, key: str) -> bool:
        if key in self._seen:
            return False
        self._seen.add(key)
        return True

    async def on_push_frame(self, data: FramePushed):
        f = data.frame
        if self._watch_task is None:
            self._watch_task = asyncio.create_task(self._watch())
        if isinstance(f, TranscriptionFrame):
            if f.text and f.text.strip():
                self._last_user = f.text.strip()
            self._last_transcript = time.monotonic()
            self._touch()
        elif isinstance(f, VADUserStartedSpeakingFrame):
            self._user_speaking = True; self._touch()
        elif isinstance(f, VADUserStoppedSpeakingFrame):
            self._user_speaking = False; self._touch()
        elif isinstance(f, BotStartedSpeakingFrame):
            self._bot_speaking = True; self._touch()
        elif isinstance(f, BotStoppedSpeakingFrame):
            self._bot_speaking = False; self._touch()
        elif isinstance(f, LLMFullResponseStartFrame):
            self._llm_busy = True; self._touch()
        elif isinstance(f, LLMFullResponseEndFrame):
            self._llm_busy = False; self._touch()
        elif isinstance(f, FunctionCallInProgressFrame):
            if f.tool_call_id not in self._active and self._once("start:" + f.tool_call_id):
                self._active[f.tool_call_id] = {"name": f.function_name, "request": self._last_user, "t0": time.monotonic(),
                                                "beat": time.monotonic()}
                if f.function_name in SLOW_TOOLS:
                    events.emit("task", id=f.tool_call_id, name=f.function_name, label=SLOW_TOOLS[f.function_name],
                                status="running", elapsed_ms=0)
            self._touch()
        elif isinstance(f, FunctionCallResultFrame):
            job = self._active.pop(f.tool_call_id, None)
            if job and job["name"] in SLOW_TOOLS and self._once("end:" + f.tool_call_id):
                events.emit("task", id=f.tool_call_id, name=job["name"], label=SLOW_TOOLS[job["name"]], status="done",
                            elapsed_ms=int((time.monotonic() - job["t0"]) * 1000))
            self._touch()
        elif isinstance(f, FunctionCallCancelFrame):
            job = self._active.pop(f.tool_call_id, None)
            if job and job["name"] in SLOW_TOOLS and self._once("cancel:" + f.tool_call_id):
                events.emit("task", id=f.tool_call_id, name=job["name"], label=SLOW_TOOLS[job["name"]], status="cancelled",
                            elapsed_ms=int((time.monotonic() - job["t0"]) * 1000))
                if job["request"]:
                    logger.info(f"[resume] interrupted {job['name']} for: {job['request']!r}; will pick it up after the interruption")
                    self._pending.append(job)
            self._touch()

    def _idle(self) -> bool:
        return (not self._user_speaking and not self._bot_speaking and not self._llm_busy and not self._active
                and time.monotonic() - self._last_activity >= IDLE_SECS
                and time.monotonic() - self._last_transcript >= 4.0)      # a split sentence's second half may still be coming

    async def _watch(self):
        while True:
            await asyncio.sleep(0.5)
            now = time.monotonic()
            for tid, job in list(self._active.items()):                      # progress heartbeat for the visual
                if job["name"] in SLOW_TOOLS and now - job["beat"] >= PROGRESS_SECS:
                    job["beat"] = now
                    events.emit("task", id=tid, name=job["name"], label=SLOW_TOOLS[job["name"]], status="running",
                                elapsed_ms=int((now - job["t0"]) * 1000))
            if self._pending and self._worker is not None and self._idle():
                job = self._pending.pop()                                    # the most recent interrupted request
                self._pending.clear()                                        # older ones are stale by now
                self._touch()
                logger.info(f"[resume] picking up: {job['request']!r}")
                events.emit("task", name=job["name"], label=SLOW_TOOLS.get(job["name"], job["name"]), status="resumed")
                await self._worker.queue_frames([LLMMessagesAppendFrame(
                    messages=[{"role": "user", "content": RESUME_PROMPT.format(req=job["request"][:300])}], run_llm=True)])
