# ai231-mex3-voice-agent

Full-duplex voice agent on a Raspberry Pi 4 (AI 231, MEX3).

## Architecture

```
 ON RPi                                              CLOUD
 Mic -> Silero VAD -> Pipecat pipeline
                       |-- asr-mcp (localhost HTTP) ---> Deepgram STT
                       |-- LLM + tool calls -----------> OpenRouter
                       |-- tts-mcp (localhost HTTP) ---> Deepgram TTS -> Speaker
                       '-- task MCPs: weather (Open-Meteo), search (Tavily),
                           site build (GitHub Pages), github (DEMO_GITHUB=1 only)
 Barge-in: VAD speech start -> cancel TTS playback + LLM stream -> listen
```

All MCP servers are our code, run on the Pi (streamable HTTP, localhost). Models are commercial APIs.

## MCP services

| Component | Server / transport | Tools | Model | Where |
|---|---|---|---|---|
| ASR | asr-mcp / HTTP | transcribe | Deepgram | Pi server |
| TTS | tts-mcp / HTTP | speak | Deepgram | Pi server |
| VAD | in-process | detect_speech | Silero | Pi, 16 kHz mono |
| Task | weather, search, site, github | see mcp_servers/ | Open-Meteo, Tavily, GitHub Pages, GitHub | Pi |

## Decision log
- Harness: Pipecat (pipeline control, built-in MCP client, barge-in/interruptions).
- ASR+TTS: Deepgram, wrapped by our own MCP servers so the servers run on the Pi.
- LLM: OpenRouter. Search: Tavily.
- Hardware: Pi 4 + room speaker; acoustic echo cancellation needed, headset is the fallback.
- GitHub MCP: fine-grained PAT, sandbox repo only, disabled unless `DEMO_GITHUB=1`.
- Prompt versioned in `prompts/`.

## Benchmark
Uses the class benchmark (trueshotjames/ai231-me3-full-duplex-benchmarking, "fdbench") instead of a bespoke tool; we only supply an adapter (`src/assistant_entry.py`). One clock (Pi monotonic). E2E = speaker out - VAD end; barge-in = playback stop - speech start. Targets: E2E 4.0 s, ASR final 0.8 s, LLM TTFT 1.5 s, TTS TTFB 0.6 s, barge-in 0.8 s. See `docs/PLAN.md`.

## Secrets
Copy `.env.example` to `.env` (git-ignored). Never commit keys.
