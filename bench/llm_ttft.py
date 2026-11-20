"""Time-to-first-token for candidate OpenRouter models, measured from the Pi's own network.
Streams a short chat completion with our real system prompt and reports median / max seconds to the first content token.
Usage: python bench/llm_ttft.py [runs]   (reads OPENROUTER_API_KEY from .env; never prints it)"""
import json
import os
import statistics
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
KEY = os.environ["OPENROUTER_API_KEY"]
SYSTEM = (ROOT / "prompts" / "system_v1.md").read_text(encoding="utf-8")
PROMPTS = ["What is five plus three?", "Tell me a short fun fact.", "Hi, how are you today?"]
MODELS = ["anthropic/claude-haiku-5.5", "openai/gpt-4.1-mini", "openai/gpt-4.1-nano",
          "google/gemini-2.5-flash-lite", "qwen/qwen3-30b-a3b-instruct-2507"]
RUNS = int(sys.argv[1]) if len(sys.argv) > 1 else 6


def ttft(client: httpx.Client, model: str, prompt: str):
    body = {"model": model, "stream": True, "max_tokens": 120,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    t0 = time.monotonic()
    with client.stream("POST", "https://openrouter.ai/api/v1/chat/completions", json=body,
                       headers={"Authorization": f"Bearer {KEY}"}) as r:
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        for line in r.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                try:
                    delta = json.loads(line[6:])["choices"][0]["delta"]
                except Exception:
                    continue
                if delta.get("content"):
                    return time.monotonic() - t0, None
    return None, "no content"


with httpx.Client(timeout=30) as client:
    for model in MODELS:
        times, err = [], None
        for i in range(RUNS):
            t, e = ttft(client, model, PROMPTS[i % len(PROMPTS)])
            if t is None:
                err = e
                break
            times.append(t)
        if times:
            print(f"{model:40s} median {statistics.median(times):.2f}s  min {min(times):.2f}  max {max(times):.2f}  "
                  f"(n={len(times)}, first {times[0]:.2f})")
        else:
            print(f"{model:40s} FAILED: {err}")
