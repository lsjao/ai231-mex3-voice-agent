# Kuya Jukebox: a full-duplex voice agent on a Raspberry Pi 4 (AI 231, MEX3)

A voice agent you can talk to naturally and interrupt, running on a Raspberry Pi 4 (8 GB). The harness is Pipecat with an MCP client;
**every tool and both speech services are MCP servers we built and run on the Pi**. Models are commercial APIs.

## Architecture

```
 ON THE RASPBERRY PI 4                                                        CLOUD (models and APIs only)
 USB mic -> Silero VAD + Smart Turn v3 -> Pipecat pipeline (MCP client)
   asr-mcp     :8101 (streaming bridge)  ------------------------------------> Deepgram nova-3 (ASR)
   LLM calls (tool calling) -----------------------------------------------> OpenRouter, openai/gpt-4.1-mini
   tts-mcp     :8102 (chunked bridge)    ------------------------------------> Deepgram Aura-2 (TTS) -> speaker
   weather-mcp :8103 (+ device clock) -----------------------------------------> Open-Meteo
   search-mcp  :8104 (rewrite -> parallel search -> read -> answer; read_page) -> Tavily + a small OpenRouter model
   music-mcp   :8105 (local ME2 playlists, ducking; fast voice commands, no LLM)
   site-mcp    :8109 (build a one-page site, publish to GitHub Pages; confirm-gated)  -> GitHub contents API
   events feed :8106 (SSE, /sessions, /replay)   visual page :8107 (docs/visual)
 Barge-in: user speech detected -> cancel TTS + LLM stream + queued audio -> listen.
```
Pi vs cloud boundary: audio capture, VAD, turn detection, all MCP servers, echo filtering, context management and music run on the Pi;
only the speech models, the LLMs, search and weather *APIs* are remote.

## MCP services

| Component | Server / transport | Tools | Model |
|---|---|---|---|
| ASR | asr-mcp :8101 / HTTP | asr_start, asr_push, asr_finish, transcribe | Deepgram nova-3 (streaming over a warm websocket) |
| TTS | tts-mcp :8102 / HTTP | speak_start, speak_next, speak_cancel, tts_warm | Deepgram Aura-2 (Orion) |
| VAD | in-process | detect_speech | Silero VAD (+ Smart Turn v3), 16 kHz |
| Weather | weather-mcp :8103 | get_weather, get_current_time | Open-Meteo; device clock |
| Search | search-mcp :8104 | web_search, read_page | Tavily + gemini-2.5-flash-lite (query rewrite, rerank, page reading) |
| Music | music-mcp :8105 | music_play/pause/resume/stop/next/previous/volume/status | local mp3 playlists |
| Site | site-mcp :8109 | publish_website(title, facts, confirmed) | gpt-4.1-mini writes the page; GitHub contents API publishes it |

## Results (class benchmark "fdbench", tools OFF, run 2026-11-21_04-16-23; Pi 4 8 GB, bare, peak 48 C, never throttled)

| Metric | Target | Mean | p95 | Result |
|---|---|---|---|---|
| E2E (end of speech -> audio out) | 4.0 s | 2.19 s | 2.81 s | pass |
| ASR final | 0.8 s | 0.31 s | 0.34 s | pass |
| LLM first token | 1.5 s | 1.20 s | 1.61 s | pass on mean, p95 slightly over |
| TTS first audio | 0.6 s | 0.41 s | 0.36 s | pass |
| Barge-in (speech -> playback stopped) | 0.8 s | 0.94 s (n=2); re-measure 0.55 s (n=5) | 1.17 s | mean passes, **tail misses** and it is variable |
| WER | 15 % | 9.8 % | n/a | pass (inflated by truncated interruption clips and number formatting) |

Live tool turns (tools ON, not part of the benchmark): plain turns about 2 to 2.6 s to first sound. Search turns say a holding phrase at about 2.4 s;
the full answer took a median of about 12 s in one live session (18 turns, range 6 to 22 s) and about 8 s in the next (4 turns). The search tool alone takes a
median of about 3 s on simple questions. E2E is counted from the VAD end; add the 0.45 s end-of-speech wait for what a person feels.

## Decision log (what we chose and why, with the evidence)
- **Pipecat** harness (MCP client, interruptions, observers). **Deepgram** for ASR+TTS behind **our own** MCP servers so the servers run on the Pi.
- **Streaming ASR**: the Pi is about 236 ms from Deepgram, so batch upload took 2.6 s; a warm websocket gives 0.3 s.
- **Chunked TTS + pre-warm**: first audio 1.4 s cold -> 0.3 s; a stale-socket bug made replies arrive one turn late and was fixed.
- **gpt-4.1-mini** over Claude Haiku 5.5 and gpt-4.1-nano: median first token 0.66 s vs 0.89 s vs 1.45 s from this Pi, and 28/28 vs 25/28 on the behaviour eval.
- **Prompt** (v1 to v10 in `prompts/`): v4 rebuilt from the official prompting guidance (role, the why, XML sections, examples, no hard-coded facts), chosen by an LLM-judge eval (56/56);
  v5 was rejected by the eval (10/14 vs 14/14). Later versions add generic rules: act on a clear request, recheck when doubted, state only what a result says,
  read a page directly when given an address, and a runtime place/time-zone context. `bench/prompt_eval.py` has no topic answers.
- **Search** is a pipeline in our own server, with no per-topic rules. The spoken question is rewritten into clean queries, a fast and a deeper Tavily search run together, low-quality domains are dropped,
  the best pages are reranked, and a small model answers **only from the page text**, naming outlets and dates. Dates and time zones are handled in code because small models mis-handle them
  (past-date tagging: 0/10 -> 10/10). Stage timings measured on the Pi: fast 1.5 s, basic 4.4 s, advanced 7.0 s, so the fast search leads and the deeper one is the hedge (tail p90 9.0 s -> 3.9 s on 12 questions).
  A search for a person by name carries a caution that results may be about someone else.
- **Echo/noise**: the agent's own voice at the Pi's 90 % speaker level scored VAD confidence 0.66-0.93 (self-interrupts) vs 0.06-0.17 at 70-80 % (measured at the time, before the speaker was turned up);
  echo-transcript filter and `scripts/echo_check.sh` for each venue. A fan alone scores 0.05. The speaker level is 90 % and the physical knob is set by hand at the venue.
- **Barge-in during tool waits**: the mic used to be muted for the whole tool call, so a 10 s search could not be interrupted. It is now muted only while the holding phrase plays (`src/mute.py`).
- **Context management**: system prompt + last 16 messages, stable prefix, slow-API fallback line after 3 s of silence, code-spoken holding phrase for tools.
- **Music** (the ME2 "Kuya Jukebox" capability): local playlists, software gain with ducking, and voice commands that skip the LLM (stop/pause/next/louder, about 1.2 s end to end including the spoken acknowledgement).
- **Scope**: a league-scores MCP server was built and then removed because it was domain-specific; the search tool is meant to be generic.
- Hardware: Pi 4 + room speaker; headset is the fallback.

## Design choices and limitations
- **No injected bias or rehearsed answers.** The prompt, the tools and the evals contain no topic-specific answers; behaviour changes are rules (ground answers in tool results, state dates and time zones, ask before public actions).
- **Search can be stale or wrong.** It reads whatever pages exist. Live prices and scores on JavaScript pages are not readable and can be hours old, so answers carry source and date. "Found" does not mean "correct", and the
  answer-key-free check in `bench/search_eval.py` only measures found / sourced / dated / latency.
- **Name-only searches can find a different person.** The agent is told to say so and ask for a distinguishing detail (or to read a page the user names, such as a profile address).
- **Publishing is gated.** `publish_website` does nothing without an explicit confirmation, does not publish unless `DEMO_GITHUB=1`, writes only to one sandbox repo with a fine-grained token, strips scripts and external resources from the generated page,
  and puts an "unverified, drafted from public search results" footer on it.
- **Known weaknesses:** the barge-in tail misses its target (p95 1.17 s); search turns take several seconds; speech recognition sometimes mishears names ("Jukebox" -> "video box").
- **Privacy and licensing:** keys live only in `~/mex3/.env` (never committed); the ME2 music files are copyrighted and are not in this repo.

## Run it
```
ssh rpi                                     # or: ssh rpi-local on a new network
bash ~/mex3/scripts/start_servers.sh        # six MCP servers + events feed + visual page; idempotent; also runs at boot (cron @reboot)
bash ~/mex3/scripts/echo_check.sh           # in the venue, stay silent ~1 min: picks the loudest safe speaker level
bash ~/mex3/scripts/run_agent.sh            # starts the agent; it says "Ready. Go ahead." when it is up
python bench/check_keys.py                  # key and credit check
python bench/search_eval.py                 # search health check (found / sourced / dated / latency), no answer key
```
Publishing to GitHub Pages is off by default: set `DEMO_GITHUB=1` in `~/mex3/.env` only for the demo. Keys live only in `~/mex3/.env` (see `.env.example`).
More: `docs/STATE.md`, `docs/VENUE_CHECKLIST.md`, `docs/DECK_CONTENT.md`.
