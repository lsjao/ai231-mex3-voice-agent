"""The voice agent: mic -> Silero VAD -> asr-mcp -> LLM (OpenRouter) -> tts-mcp -> speaker, with barge-in.

build(transport, log_dir) is the entry point the class benchmark (fdbench) needs: the benchmark passes its own
websocket transport; run locally (`python -m src.agent`) we use the Pi's mic and speaker.
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import WorkerRunner
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.services.mcp_service import MCPClient
from pipecat.services.openrouter.llm import OpenRouterLLMService
from pipecat.transports.base_transport import TransportParams
from mcp.client.session_group import StreamableHttpParameters

from src.guard import TurnGuard
from src.mcp_services import McpSTT, McpTTS
from src.trace import TraceObserver

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-4.1-mini")
STOP_SECS = float(os.environ.get("VAD_STOP_SECS", "0.7"))  # silence that ends a turn: lower = faster, but cuts pauses
VAD_START = float(os.environ.get("VAD_START_SECS", "0.35"))  # continuous speech needed before barge-in: ignores clicks/coughs
VAD_CONF = float(os.environ.get("VAD_CONFIDENCE", "0.8"))  # higher = ignores background noise/music better
AUDIO_IN_RATE = 16000   # fdbench requires 16 kHz input
AUDIO_OUT_RATE = 24000
PROMPT_VERSION = "v1"
BENCH = os.environ.get("BENCH") == "1"  # benchmark mode: no tools (class convention: tools/agent calls off)
TASK_SERVERS = {"weather-mcp": "http://127.0.0.1:8103/mcp", "search-mcp": "http://127.0.0.1:8104/mcp"}


def load_prompt() -> str:
    return (ROOT / "prompts" / f"system_{PROMPT_VERSION}.md").read_text(encoding="utf-8").strip()


async def make_pipeline(transport):
    stt = McpSTT()
    tts = McpTTS(sample_rate=AUDIO_OUT_RATE)
    llm = OpenRouterLLMService(
        api_key=os.environ["OPENROUTER_API_KEY"],
        settings=OpenRouterLLMService.Settings(model=LLM_MODEL, max_tokens=300, temperature=0.6),
    )
    clients, tools = [], None
    if not BENCH:
        for name, url in TASK_SERVERS.items():
            try:
                c = MCPClient(StreamableHttpParameters(url=url))
                await c.start()
                t = await c.tools()
                clients.append(c)
                tools = t if tools is None else ToolsSchema(standard_tools=tools.standard_tools + t.standard_tools)
                logger.info(f"tools from {name}: {[f.name for f in t.standard_tools]}")
            except Exception as e:
                logger.warning(f"{name} unavailable, continuing without it: {e}")
    extra = {"tools": tools} if tools is not None else {}  # BENCH mode: no tools (tools=None is invalid)
    context = LLMContext(messages=[{"role": "system", "content": load_prompt()}], **extra)
    pair = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(params=VADParams(confidence=VAD_CONF, start_secs=VAD_START, stop_secs=STOP_SECS)),
        ),
    )
    pipeline = Pipeline([
        transport.input(),
        stt,
        pair.user(),
        TurnGuard(),
        llm,
        tts,
        transport.output(),
        pair.assistant(),
    ])
    return pipeline, clients


async def build(transport, log_dir: Path):
    pipeline, clients = await make_pipeline(transport)
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(audio_in_sample_rate=AUDIO_IN_RATE, audio_out_sample_rate=AUDIO_OUT_RATE,
                              enable_metrics=True, enable_usage_metrics=True),
        observers=[TraceObserver()],
    )
    runner = WorkerRunner(handle_sigint=False)

    async def run():
        try:
            await runner.add_workers(worker)
            await runner.run()
        finally:
            for c in clients:
                await c.close()

    async def cancel():
        await worker.cancel()

    return run(), cancel


def describe() -> dict:
    return {"ASR": "Deepgram nova-3 (streaming, via asr-mcp)", "LLM": LLM_MODEL,
            "TTS": "Deepgram aura-2 (via tts-mcp)", "VAD": "Silero v5"}


async def main():
    from src.local_audio import SdAudioTransport
    transport = SdAudioTransport(TransportParams(
        audio_in_enabled=True, audio_out_enabled=True,
        audio_in_sample_rate=AUDIO_IN_RATE, audio_out_sample_rate=AUDIO_OUT_RATE,
    ))
    run, _cancel = await build(transport, ROOT / "logs")
    logger.info(f"agent ready: model={LLM_MODEL} stop_secs={STOP_SECS}")
    await run


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, level=os.environ.get("LOG_LEVEL", "INFO"))
    asyncio.run(main())
