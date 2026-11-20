# MEX3 deck content (2-page template, sections 1-6). Benchmark numbers are from the final run 2026-11-21_04-16-23.

## 1. SYSTEM DIAGRAM (see docs/agent_visual.html for the interactive version)
Mic (USB) -> Silero VAD + Smart Turn v3 (Pi) -> asr-mcp :8101 -> LLM (OpenRouter, openai/gpt-4.1-mini) -> tts-mcp :8102 -> speaker (3.5 mm)
Task MCP servers (all ours, all on the Pi, streamable HTTP on localhost): weather :8103 (Open-Meteo), search :8104 (Tavily), music :8105 (local ME2 mp3 playlists).
Cloud boundary: Deepgram (ASR nova-3 streaming, TTS Aura-2), OpenRouter (LLM), Tavily, Open-Meteo. Everything else runs on the Raspberry Pi 4 (8 GB).
Barge-in: user speech detected -> cancel TTS playback + drop queued audio + abort the LLM stream -> listen. Music ducks while anyone talks.
Harness: Pipecat 1.16 (MCP client). Started at boot by cron; servers restart safely (idempotent start script).

## 2. PROMPT (version it): prompts/system_v1.md .. v4.md, production = v4
v1 Pip persona, speaking rules -> v2 tools + Kuya Jukebox persona -> v3 code-spoken holding phrase, recency rules, runtime date -> v4 rebuilt from the
official prompting guidance: one-sentence role, the WHY behind each rule, positive phrasing, XML sections, 3-5 diverse examples, tool-use policy,
no hard-coded facts, date injected into a <context> block. v5 (extra rules) was REJECTED by the eval (10/14 vs 14/14).
Excerpt: "Everything you write is turned into speech ... For anything that may have changed, call the matching tool first and answer from what it
returns ... If a result is old, off-topic or inconclusive, say you could not find a reliable current answer."
Eval (bench/prompt_eval.py, LLM judge, 14 generic scenarios x 4 runs): v4 + tool-description guard = 56/56.

## 3. CONTEXT ENGINEERING
GOES IN: system prompt + persona (~560 tokens) | ASR final per VAD turn | VAD/turn events | MCP tool results (past dates tagged in code) | runtime date block | tool schemas.
MANAGED: rolling window (system + last 16 messages, never starting mid tool-exchange) | stable prefix never edited (cache-friendly TTFT) |
idle -> listen -> think -> speak | on barge-in: cancel TTS, drop stale audio, clear queued speech | echo filter drops transcripts that are fragments of the agent's own speech |
mic muted during tool calls | music ducked while anyone talks | context size logged per run (median 1106, max 2066 tokens BEFORE trimming).

## 4. MCP SERVICES / MODEL SERVING (one table)
| Component | MCP server / transport | Tools | Model | Served where / notes |
| ASR | asr-mcp :8101 / HTTP | asr_start, asr_push, asr_finish, transcribe | Deepgram nova-3 (streaming) | Pi server; persistent websocket, audio streamed while speaking, final ~0.3 s after end |
| TTS | tts-mcp :8102 / HTTP | speak_start, speak_next, speak_cancel, tts_warm | Deepgram Aura-2 (Orion) | Pi server; first audio ~0.3-0.4 s; cancel on barge-in |
| LLM | (harness MCP client) | function calling | openai/gpt-4.1-mini via OpenRouter | commercial API; streaming |
| VAD | in-process | detect_speech | Silero VAD + Smart Turn v3 | Pi on-device, 16 kHz mono |
| Task: weather | weather-mcp :8103 | get_weather | Open-Meteo (no key) | Pi server |
| Task: search | search-mcp :8104 | web_search | Tavily | Pi server; recency-biased; tags past dates |
| Task: music | music-mcp :8105 | music_play/pause/resume/stop/next/previous/volume/status | local mp3 playlists (ME2) | Pi server; software gain, ducking |

## 5. EVALUATION & BENCHMARK (class tool fdbench; one clock = Pi monotonic; tools OFF per class convention)
FINAL run 2026-11-21_04-16-23 (Pi 4 8 GB, bare, peak 48 C, never throttled, Wi-Fi, 7 ms benchmark link; 10 phrases x 3 runs + 1 Full-Duplex-Bench round; tools OFF):
| Metric | Definition | Target | Mean | p95 | n | Result |
| E2E latency | end of speech -> audio out | < 4.0 s | 2.19 s | 2.81 s | 30 | PASS |
| ASR final | end of speech -> transcript | < 0.8 s | 0.31 s | 0.34 s | 30 | PASS |
| LLM TTFT | transcript -> first token | < 1.5 s | 1.20 s | 1.61 s | 30 | PASS (mean); p95 slightly over |
| TTS TTFB | text -> first audio chunk | < 0.6 s | 0.41 s | 0.36 s | 30 | PASS |
| Barge-in | speech -> playback stopped | < 0.8 s | 0.94 s | 1.24 s | 2 | **MISS** (n=2, spread 0.6-1.24 s; an earlier run measured 0.59 s) |
| WER | ASR accuracy on test set | < 15 % | 9.8 % | n/a | 30 | PASS (see note) |
Honest notes: barge-in has only 2 samples and missed the target; a re-measure with more rounds is planned. WER rose from 4.2 % (earlier run) to 9.8 % partly because this run drew
different test phrases and the scorer counts "20 minutes" vs "twenty minutes", "July 4" vs "07/04" and "orchids" vs "orchid" as errors, but 2 of 30 transcripts also lost their last word (real).
Barge-in re-measure (run 2026-11-21_05-00-29, 3 rounds, n=5 interruption clips, tools off): mean 0.55 s, median 0.32 s, p95 1.17 s, min 0.16 s, max 1.31 s.
Verdict: the mean PASSES the 0.8 s target, but the tail does not (p95 1.17 s) and it is highly variable; 5 samples is still small. The 0.94 s in the main run was one slow sample (n=2), not a typical value.
Earlier run (02:24): E2E 2.39 s (p95 4.17), ASR final 0.26 s, LLM TTFT 1.51 s (p95 3.46), TTS TTFB 0.41 s, barge-in 0.59 s (n=2), WER 4.2 %. The context trim (last 16 messages) and the model switch
are what brought the p95 tail down.
Reported separately (live, tools ON, not part of the class benchmark): plain turns ~2.0-2.6 s to first sound; search turns: holding phrase ~2.4 s, full answer ~5-8 s.
Honest note: E2E is counted from VAD end; add the end-of-speech wait (0.45 s) for the delay a person feels.

## DEMO (2-3 min script): real tasks, natural turns, barge-in, live MCP call, recovery when an API is slow
1 "Hi Kuya Jukebox" -> greeting | 2 "What's the weather in Manila?" (live MCP call, holding phrase) | 3 "Play some focus music" ... "next song" ...
music ducks as I talk | 4 ask a long question, interrupt mid-sentence ("Okay, stop") | 5 "What's the latest news about <topic>?" (search; slow-connection line
if the API stalls) | 6 "What year is it?" "Stop the music." Backup: recorded video + phone hotspot.

## 6. CHALLENGES (one per row: fix + the measurement that proves it)
| Challenge | Fix | Proof |
| Pi is ~236 ms from Deepgram: batch ASR took 2.6 s | streaming ASR over a warm websocket | ASR final 2.6 s -> 0.3-0.5 s |
| TTS cold start + replies arriving one turn late | pre-warm connection; drain stale socket messages; chunked speak | first audio 1.4 s -> 0.3 s; desync gone in live test |
| First words clipped by my barge-in debounce | 900 ms audio pre-roll > VAD start delay | WER 21.3 % -> 4.2 % (class benchmark) |
| Agent interrupted itself / answered itself | measured the cliff (speaker 90 % -> echo conf 0.9; 80 % -> 0.17); 80 % default; echo-transcript filter; mic mute during tools; venue echo_check.sh | live run: zero phantom turns with fan on |
| "Latest" questions returned old facts; small model mis-compares dates | recency-biased search + deeper depth for news + past-date tagging in code | past-date eval 0/10 -> 10/10; correct election answers |
| Dead air while tools run / slow APIs | code-spoken holding phrase; slow-connection guard (3 s) | guard fired live on a 5 s LLM stall |
| Name-only web search returns strangers | caution in the tool description; confirm identity | person-search eval 4/4; no regression (56/56) |
| Prompt change made things worse | eval harness caught v5 | 10/14 vs 14/14 -> v5 rejected |
| ALSA volumes reset on reboot; servers must start unattended | start script re-applies levels; cron @reboot | real reboot test: 4/4 servers up, nothing by hand |

## REFERENCES
modelcontextprotocol.io | Pipecat docs | Deepgram docs | Full-Duplex-Bench (Lin et al. 2025/2026) | class fdbench repo | repo: github.com/lsjao/ai231-mex3-voice-agent
