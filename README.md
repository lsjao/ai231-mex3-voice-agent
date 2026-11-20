# Kuya Jukebox: a full-duplex voice agent on a Raspberry Pi 4 (AI 231, MEX3)

A voice agent you can talk to naturally and interrupt, running on a Raspberry Pi 4 (8 GB). The harness is Pipecat with an MCP client;
**every tool and both speech services are MCP servers we built and run on the Pi**. Models are commercial APIs.

## Architecture

```
 ON THE RASPBERRY PI 4                                                        CLOUD (models only)
 USB mic -> Silero VAD + Smart Turn v3 -> Pipecat pipeline (MCP client)
   asr-mcp    :8101  (streaming bridge)  ------------------------------------> Deepgram nova-3 (ASR)
   LLM calls (tool calling) -----------------------------------------------> OpenRouter, openai/gpt-4.1-mini
   tts-mcp    :8102  (chunked bridge)    ------------------------------------> Deepgram Aura-2 (TTS) -> speaker
   weather-mcp :8103 ------------------------------------------------------> Open-Meteo
   search-mcp  :8104 (recency-biased, past-date tagging) -------------------> Tavily
   music-mcp   :8105 (local ME2 playlists, ducking; fast voice commands)
   events feed :8106 (SSE, /sessions, /replay)   visual page :8107 (docs/visual)
 Barge-in: user speech detected -> cancel TTS + LLM stream + queued audio -> listen.
```
Pi vs cloud boundary: audio capture, VAD, turn detection, all MCP servers, echo filtering, context management and music run on the Pi;
only the ASR, LLM, TTS, search and weather *models/APIs* are remote.

## MCP services

| Component | Server / transport | Tools | Model |
|---|---|---|---|
| ASR | asr-mcp :8101 / HTTP | asr_start, asr_push, asr_finish, transcribe | Deepgram nova-3 (streaming over a warm websocket) |
| TTS | tts-mcp :8102 / HTTP | speak_start, speak_next, speak_cancel, tts_warm | Deepgram Aura-2 (Orion) |
| VAD | in-process | detect_speech | Silero VAD (+ Smart Turn v3), 16 kHz |
| Weather | weather-mcp :8103 | get_weather | Open-Meteo |
| Search | search-mcp :8104 | web_search | Tavily |
| Music | music-mcp :8105 | music_play/pause/resume/stop/next/previous/volume/status | local mp3 playlists |

## Results (class benchmark "fdbench", tools OFF, run 2026-11-21_04-16-23; Pi 4 8 GB, bare, peak 48 C, never throttled)

| Metric | Target | Mean | p95 | Result |
|---|---|---|---|---|
| E2E (end of speech -> audio out) | 4.0 s | 2.19 s | 2.81 s | pass |
| ASR final | 0.8 s | 0.31 s | 0.34 s | pass |
| LLM first token | 1.5 s | 1.20 s | 1.61 s | pass on mean, p95 slightly over |
| TTS first audio | 0.6 s | 0.41 s | 0.36 s | pass |
| Barge-in (speech -> playback stopped) | 0.8 s | 0.94 s (n=2); re-measure 0.55 s (n=5) | 1.17 s | mean passes, **tail misses** and it is variable |
| WER | 15 % | 9.8 % | n/a | pass (inflated by truncated interruption clips and number formatting) |

Live tool turns (not in the benchmark): plain turns about 2 to 2.6 s to first sound; search turns say a holding phrase at about 2.4 s and answer in about 5 to 8 s.
E2E is counted from the VAD end; add the 0.45 s end-of-speech wait for what a person feels.

## Decision log (what we chose and why, with the evidence)
- **Pipecat** harness (MCP client, interruptions, observers). **Deepgram** for ASR+TTS behind **our own** MCP servers so the servers run on the Pi.
- **Streaming ASR**: the Pi is about 236 ms from Deepgram, so batch upload took 2.6 s; a warm websocket gives 0.3 s.
- **Chunked TTS + pre-warm**: first audio 1.4 s cold -> 0.3 s; a stale-socket bug made replies arrive one turn late and was fixed.
- **gpt-4.1-mini** over Claude Haiku 5.5: 0.73 s vs 1.32 s median first token measured from this Pi.
- **Prompt v4** (role, why, XML sections, examples, no hard-coded facts) chosen by an LLM-judge eval (56/56); v5 was rejected (10/14 vs 14/14). See `prompts/` and `bench/prompt_eval.py`.
- **Echo/noise**: the agent's own voice at speaker 90 % scored VAD confidence 0.66-0.93 (self-interrupts) vs 0.06-0.17 at 70-80 %; default 80 %, echo-transcript filter, mic muted during tool calls, `scripts/echo_check.sh` for each venue. A fan alone scores 0.05.
- **Search correctness in code, not the prompt**: small models mis-compare dates (0/10); tagging past dates in the tool result made it 10/10. Recency-biased search and a caution on name-only person searches.
- **Context management**: system prompt + last 16 messages, stable prefix, slow-API fallback line after 3 s of silence, code-spoken holding phrase for tools.
- **Music** (the ME2 "Kuya Jukebox" capability): local playlists, software gain with ducking, and voice commands that skip the LLM (stop/pause/next/louder, about 0.4 s).
- Hardware: Pi 4 + room speaker (echo handling above); headset is the fallback. The GitHub tool stays disabled behind `DEMO_GITHUB=0`.

## Run it
```
ssh rpi                                     # or: ssh rpi-local on a new network
bash ~/mex3/scripts/start_servers.sh        # five MCP servers + events feed + visual page; idempotent; also runs at boot (cron @reboot)
bash ~/mex3/scripts/echo_check.sh           # in the venue, stay silent ~1 min: picks the loudest safe speaker level
bash ~/mex3/scripts/run_agent.sh            # starts the agent; the ringtone means ready
python bench/check_keys.py                  # key and credit check
```
Keys live only in `~/mex3/.env` (see `.env.example`); never committed. Music files are copyrighted and are not in this repo. More: `docs/STATE.md`, `docs/VENUE_CHECKLIST.md`, `docs/DECK_CONTENT.md`.
