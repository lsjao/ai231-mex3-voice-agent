"""Text-only test (no audio) of background tools: ask a question that triggers a search, interrupt it with a different question,
and print a timeline. With ASYNC_TOOLS unset the search is cancelled and never answered; with ASYNC_TOOLS=web_search the other
question is answered at once and the search result is spoken when it arrives.   Usage: ASYNC_TOOLS=web_search python bench/async_tool_test.py"""
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from loguru import logger
logger.remove()

from pipecat.frames.frames import (FunctionCallInProgressFrame, FunctionCallResultFrame, InterruptionFrame, LLMFullResponseEndFrame,
                                   LLMMessagesAppendFrame, LLMTextFrame)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import WorkerRunner
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.openrouter.llm import OpenRouterLLMService

from src.agent import LLM_MODEL, ASYNC_TOOLS, load_prompt, load_task_tools
from src.resume import ResumeObserver

T0 = time.monotonic()
LOG = []
text_buf = []


def mark(kind, what=""):
    LOG.append((time.monotonic() - T0, kind, what))
    print(f"{time.monotonic() - T0:6.1f}s  {kind:10s} {what}", flush=True)


class Sink(FrameProcessor):
    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMTextFrame):
            text_buf.append(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame):
            if text_buf:
                mark("AGENT", "".join(text_buf).strip()[:200]); text_buf.clear()
        elif isinstance(frame, FunctionCallInProgressFrame):
            mark("tool-start", frame.function_name)
        elif isinstance(frame, FunctionCallResultFrame):
            mark("tool-end", frame.function_name)
        await self.push_frame(frame, direction)


async def main():
    print("ASYNC_TOOLS =", sorted(ASYNC_TOOLS) or "(none: tools cancel on interruption)")
    llm = OpenRouterLLMService(api_key=os.environ["OPENROUTER_API_KEY"],
                               settings=OpenRouterLLMService.Settings(model=LLM_MODEL, max_tokens=300, temperature=0.6))
    clients, tools = await load_task_tools()
    context = LLMContext(messages=[{"role": "system", "content": load_prompt()}], tools=tools)
    pair = LLMContextAggregatorPair(context)
    resume = ResumeObserver() if os.environ.get("RESUME") == "1" else None
    worker = PipelineWorker(Pipeline([pair.user(), llm, Sink(), pair.assistant()]), params=PipelineParams(enable_metrics=False),
                            observers=[resume] if resume else [])
    if resume:
        resume.attach(worker)
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    run = asyncio.create_task(runner.run())
    await asyncio.sleep(1.0)
    q1, q2 = sys.argv[1] if len(sys.argv) > 1 else "What is the latest news about the Mars rover?", "Quick question: what is twelve times eleven?"
    mark("USER", q1)
    if resume:
        resume.note_user(q1)
    await worker.queue_frames([LLMMessagesAppendFrame(messages=[{"role": "user", "content": q1}], run_llm=True)])
    for _ in range(60):                                          # wait until the search itself has started, then interrupt it
        await asyncio.sleep(0.25)
        if any(k == "tool-start" and "web_search" in w for _, k, w in LOG):
            break
    await asyncio.sleep(1.0)
    mark("USER", q2 + "   (interrupts the search)")
    if resume:
        resume.note_user(q2)
    await worker.queue_frames([InterruptionFrame(), LLMMessagesAppendFrame(messages=[{"role": "user", "content": q2}], run_llm=True)])
    await asyncio.sleep(32)
    mark("end")
    await worker.cancel()
    for c in clients:
        await c.close()
    run.cancel()

asyncio.run(main())
