# MEX3 plan (12-hour build)

Hard deadline: 2026-11-21 1:59 PM. Cut scope before cutting sleep or the demo backup.

## Design constraints taken from the class benchmark (trueshotjames/ai231-me3-full-duplex-benchmarking)
- Our app must expose `build(transport, log_dir) -> (run_coroutine, cancel_fn)` and build its Pipecat pipeline around a
  transport passed in from outside (benchmark swaps in a websocket transport; demo uses the local audio transport).
- Input sample rate 16 kHz mono. Needs Pipecat >= 1.13 and `pipecat-ai[websocket]` in the Pi venv.
- Stage marks (VAD end, ASR final, LLM TTFT, TTS TTFB) are read from standard Pipecat frames, so our custom STT/TTS
  services (which call asr-mcp / tts-mcp) MUST push `TranscriptionFrame`, `TTSStartedFrame`, `TTSAudioRawFrame`,
  and `LLMTextFrame` comes from the stock LLM service. Do not invent frame types.
- Run model: Pi runs `launch_assistant.py --url ws://LAPTOP-IP:8791`; laptop runs `python -m fdbench`. Laptop firewall must allow TCP 8791 and UDP 8792.
- Targets: E2E 4.0 s, ASR final 0.8 s, LLM TTFT 1.5 s, TTS TTFB 0.6 s, barge-in 0.8 s, WER 15%.
- Benchmark runs with tools/agent calls disabled (add a BENCH flag); tools stay live in the demo.

## Design decisions (latency vs effort)
- asr-mcp: `transcribe(audio)` on VAD/turn end, Deepgram nova-3 prerecorded REST. Batch, not streaming: simplest, should fit the 0.8 s target for short utterances. Upgrade to streaming only if ASR final misses target.
- tts-mcp: `speak(text)` per sentence, Deepgram Aura-2, returns PCM. Sentence-level chunks keep TTFB near one REST round trip; barge-in cancels the in-flight call and drops queued audio.
- VAD: Silero in-process; turn end: Smart Turn v3 if it installs cleanly on the Pi 4, else VAD silence timeout.
- Echo: wired speaker, mic away from it, Pipecat WebRTC AEC if available for our version; headset is the demo fallback.
- LLM: non-reasoning model via OpenRouter (reasoning models time out; chat advice). Cap replies ~400 tokens.
- Context: stable prefix (system prompt + tool schemas) never edited; log context tokens per run.

## Order of work
| # | Block | Exit check |
|---|---|---|
| 0 | Pi reachable; venv + pipecat; audio + VAD smoke | `ssh rpi echo ok`; VAD prints speech segments |
| 1 | asr-mcp (:8101), tts-mcp (:8102) as streamable-HTTP MCP, systemd units | curl-style MCP call returns text / audio |
| 2 | Pipecat pipeline: VAD -> asr -> LLM -> tts, barge-in, `build()` entry | spoken round trip; interrupt stops playback |
| 3 | weather (Open-Meteo), search (Tavily) MCP tools | demo questions answered via live tool call |
| 4 | Benchmark: 1 round, then stage test; fix worst stage | results.html with mean/p95 vs targets |
| 5 | Deck: fill 2-page template; record backup demo video | PDF + video exist |
| 6 | If time: site-build MCP (GitHub Pages), github MCP (DEMO_GITHUB=1) | optional |

## Demo script (2-3 min)
Ask for a longer task, ask a quick weather/search question meanwhile, interrupt mid-reply with a correction,
pause deliberately, then ask a follow-up. Backup: recorded video (venue internet is unreliable).

## Risks
- Pi unreachable (IP changed): need current IP.
- Python 3.13 wheels on Pi (onnxruntime/numpy): fall back to uv-managed 3.12.
- Echo / self-hearing: most common failure in the class; test with the real speaker early (block 2).
- Network at venue: hotspot + video backup.
