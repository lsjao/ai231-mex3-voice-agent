"""Text-only chat through the real agent pieces (real LLM, real MCP tools, no audio): each argument is one user turn.
Prints the agent's replies and tool calls with times.   Usage: python bench/text_chat.py "first line" "second line" ..."""
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
import warnings
warnings.filterwarnings("ignore")

from pipecat.frames.frames import (FunctionCallInProgressFrame, FunctionCallResultFrame, LLMFullResponseEndFrame,
                                   LLMMessagesAppendFrame, LLMTextFrame)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import WorkerRunner
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.openrouter.llm import OpenRouterLLMService

from src.agent import LLM_MODEL, load_prompt, load_task_tools

T0 = time.monotonic()
buf, state = [], {"pending": 0, "replied": asyncio.Event(), "last": time.monotonic()}


def mark(kind, what=""):
    state["last"] = time.monotonic()
    print(f"{time.monotonic() - T0:6.1f}s  {kind:10s} {what}", flush=True)


class Sink(FrameProcessor):
    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMTextFrame):
            buf.append(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame):
            if buf:
                mark("AGENT", "".join(buf).strip()[:300]); buf.clear()
            if state["pending"] == 0:
                state["replied"].set()
        elif isinstance(frame, FunctionCallInProgressFrame):
            state["pending"] += 1; mark("tool-start", f"{frame.function_name} {str(frame.arguments)[:140]}")
        elif isinstance(frame, FunctionCallResultFrame):
            state["pending"] = max(0, state["pending"] - 1); mark("tool-end", f"{frame.function_name} -> {str(frame.result)[:200]}")
        await self.push_frame(frame, direction)


async def main():
    llm = OpenRouterLLMService(api_key=os.environ["OPENROUTER_API_KEY"],
                               settings=OpenRouterLLMService.Settings(model=LLM_MODEL, max_tokens=300, temperature=0.6))
    clients, tools = await load_task_tools()
    context = LLMContext(messages=[{"role": "system", "content": load_prompt()}], tools=tools)
    pair = LLMContextAggregatorPair(context)
    worker = PipelineWorker(Pipeline([pair.user(), llm, Sink(), pair.assistant()]), params=PipelineParams(enable_metrics=False))
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    run = asyncio.create_task(runner.run())
    await asyncio.sleep(1.0)
    for line in sys.argv[1:]:
        state["replied"].clear()
        mark("USER", line)
        await worker.queue_frames([LLMMessagesAppendFrame(messages=[{"role": "user", "content": line}], run_llm=True)])
        t_start = time.monotonic()
        while time.monotonic() - t_start < 90:                    # a turn is over when nothing has happened for 7 s
            await asyncio.sleep(0.5)
            if state["pending"] == 0 and time.monotonic() - state["last"] > 7:
                break
    await worker.cancel()
    for c in clients:
        await c.close()
    run.cancel()

asyncio.run(main())
