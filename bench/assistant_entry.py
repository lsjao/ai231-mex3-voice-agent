"""Adapter: how the class benchmark (fdbench) starts OUR assistant. Copied to ~/mex3/fd-benchmark/assistant_entry.py
on the Pi. Benchmark mode runs with tools OFF (class convention: tools and agent calls disabled), via BENCH=1."""
import os
from pathlib import Path

os.environ["BENCH"] = "1"          # must be set before src.agent is imported (it reads it at import time)

PROJECT_MARKER = "src/agent.py"    # identifies the project folder (~/mex3)


def audio_rates() -> tuple[int, int]:
    return 16000, 24000            # input must be 16 kHz for fdbench; our TTS plays at 24 kHz


def describe() -> dict:
    from src.agent import describe as d
    return d()


async def build(transport, log_dir: Path):
    from src.agent import build as agent_build
    return await agent_build(transport, log_dir)
