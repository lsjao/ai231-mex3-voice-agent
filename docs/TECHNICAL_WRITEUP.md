# Kuya Jukebox: technical write-up (MEX3)

A full-duplex voice agent on a Raspberry Pi 4 (8 GB). You talk to it, you can interrupt it, and it uses tools: weather, a clock and time-zone converter, web search, page reading, music, and publishing a web page to GitHub Pages. Every tool and both speech services are **MCP servers we wrote and run on the Pi**. The language and speech models are commercial APIs.

Repo: `github.com/lsjao/ai231-mex3-voice-agent` (final tags `final-demo-v1`, `final-demo-v2`).

---

## 1. The flow, step by step (what is used for which)

```
                          ON THE RASPBERRY PI 4                                    CLOUD
  USB mic ──► capture (sounddevice, 48 kHz → 16 kHz)
        │
        ▼
  Silero VAD v5 + Smart Turn v3  ──(user speaks while agent talks)──► BARGE-IN
        │  "is someone speaking / has the turn ended?"                  cancel TTS, drop queued audio,
        ▼                                                               abort LLM stream, listen
  asr-mcp :8101 ───────────────── streaming websocket ──────────────► Deepgram nova-3 (speech → text)
        │  final transcript ~0.3 s after speech ends
        ├──► echo filter (drop text that is the agent's own voice)
        ├──► FAST PATH: "next song / stop the music / louder"  ──► music-mcp directly (no LLM)
        ▼
  Pipecat 1.16 pipeline (MCP client) ───────────────────────────────► OpenRouter: openai/gpt-4.1-mini
        │  system prompt v13 + last 16 messages + runtime date/place
        │  function calling:
        ├──► weather-mcp :8103  get_weather, get_current_time, convert_time ──► Open-Meteo, zoneinfo
        ├──► search-mcp  :8104  web_search, read_page ──► Tavily + a small model (gemini-2.5-flash-lite)
        ├──► music-mcp   :8105  play/pause/next/volume… (local ME2 mp3 playlists, ducking)
        └──► site-mcp    :8109  create_public_repo, publish_website ──► GitHub API (+ gpt-4.1-mini writes the page)
        ▼
  tts-mcp :8102 ─────────────── chunked, pre-warmed websocket ──────► Deepgram Aura-2 (text → speech)
        ▼
  speaker (3.5 mm)              holding phrases ("Let me look that up.") are spoken by OUR code, not the model

  events feed :8106 (SSE + session JSONL)  ──►  live visual :8107          start at boot: cron @reboot
```

### What each piece is for

| Stage | What we used | Why this, in one line |
|---|---|---|
| Audio in | USB condenser mic, `sounddevice`, 48 kHz resampled to 16 kHz | The mic runs at 48 kHz; models want 16 kHz mono |
| Voice activity + turn end | Silero VAD v5 (confidence 0.8, start 0.35 s, stop 0.45 s) + Smart Turn v3 | Decides when you start and stop talking; the 0.8 gate ignores room noise and music |
| Speech to text | `asr-mcp` → Deepgram nova-3, streaming over one open websocket, key terms ("Kuya Jukebox", "Lacuata"), 900 ms audio pre-roll | Streaming gives a final transcript about 0.3 s after you stop; the pre-roll stops the first word being clipped |
| Echo handling | Transcript echo filter, volume gate, `scripts/echo_check.sh` per room | The agent must not answer its own voice |
| Fast commands | Regex router → `music-mcp` directly | "Stop the music" should not wait for an LLM (about 1.2 s including the spoken "Stopped.") |
| Agent / orchestration | Pipecat 1.16 pipeline with an MCP client | Handles interruptions, tool calls and streaming |
| LLM | `openai/gpt-4.1-mini` via OpenRouter, 4 s retry if a request stalls | Fastest first token that still followed our rules (see section 3) |
| Prompt | Versioned `prompts/system_v1…v13.md`, XML sections, no hard-coded facts, today's date and place injected | Rules, not answers; tested by an automated judge |
| Context | System + last 16 messages (never cut mid tool call) | Keeps the first token fast and the cost low |
| Weather and time | `weather-mcp` (Open-Meteo, device clock, `convert_time`) | Time-zone arithmetic is done in code because small models get it wrong |
| Search | `search-mcp`: rewrite → fast + deep Tavily search in parallel → drop low-quality domains → rerank → a small model answers only from the page text → retry once if "not found". Also `read_page` | Search results are pages, not answers; reading them in code gives sourced, dated answers |
| Music | `music-mcp`: local playlists, software gain, ducks while anyone talks | The ME2 "Kuya Jukebox" capability |
| Website publishing | `site-mcp`: builds a one-page site, can create a public repo with Pages, publishes via the GitHub API. Needs confirmation, a switch (`DEMO_GITHUB`), caps, sanitised HTML | Public actions are hard to undo, so each one has a gate |
| Text to speech | `tts-mcp` → Deepgram Aura-2, chunked, pre-warmed | First audio about 0.4 s; cancels instantly on barge-in |
| Interruptions | Cancel TTS and the LLM stream, mute the mic only while the holding phrase plays, resume a cancelled search afterwards | Fast to stop, and the interrupted question is not lost |
| Observability | `TraceObserver` → session JSONL → SSE → visual, plus a `task` event for slow tools | One source of truth for latency, the demo visual and replay |
| Operations | cron `@reboot`, idempotent `start_servers.sh`, `demo_github.sh on/off`, key checks | Survives a reboot with nothing done by hand |

---

## 2. Wins

- **Speech is fast and stable.** Streaming recognition brought the transcript from 2.6 s down to 0.3 s. Text-to-speech first audio went from 1.4 s cold to 0.3–0.4 s.
- **Five of six class-benchmark targets pass**, with the fast stages (ASR 0.31 s, TTS 0.41 s) well inside their targets.
- **The first words are no longer lost.** A 900 ms pre-roll fixed clipped first words: WER went from 21.3 % to 4.2 % in one run.
- **Search answers are sourced and dated.** On 10 fresh, untuned questions: 10/10 found, 10/10 name a source, 10/10 carry a date. The tail of the slowest searches dropped from 9.0 s to 3.9 s (p90).
- **Dates and time zones are done in code.** Past-date handling went from 0/10 (model) to 10/10 (code). `convert_time` gave the right answer in every live and text test we ran.
- **Interruptions are handled end to end.** The agent stops within a fraction of a second, you can interrupt even a 10 s search, and the interrupted question is picked back up afterwards. We saw this live.
- **A test harness that catches regressions.** The prompt eval caught a bad prompt version (v5, 10/14 versus 14/14) that "felt" fine.
- **Safe by construction.** No secrets in the repo or its history. Publishing needs a confirmation, a switch, a capped number of repositories, and sanitised HTML with an "unverified" footer.
- **It runs unattended.** After a reboot all servers come back, and audio levels are re-applied.

---

## 3. "We tried X, but went with Y because Z"

| # | We tried | We went with | Because (with the measurement) |
|---|---|---|---|
| 1 | Sending each sentence to the speech service as one file | **Streaming audio over an open websocket** | The Pi is about 236 ms from the service; one file took 2.6 s, streaming gives 0.3 s |
| 2 | Claude Haiku 5.5 and GPT-4.1-nano | **GPT-4.1-mini** | First token 0.66 s (mini) vs 0.89 s (Haiku) vs 1.45 s (nano), and 28/28 on our rule test versus 25/28 for Haiku |
| 3 | A longer prompt with extra rules (v5) | **A short prompt with clear sections (v4 style)** | The eval showed v5 got worse, 10/14 versus 14/14. We keep each version and test it |
| 4 | Trusting the search provider's own summary | **A small model that reads the page text and answers only from it** | The summary was wrong in several of our spot checks. Reading pages gives sources and dates |
| 5 | Deep search first, then retry | **Fast and deep search in parallel** | Measured stages: fast 1.5 s, basic 4.4 s, advanced 7.0 s. Running both cut the slowest searches from 9.0 s to 3.9 s (p90) |
| 6 | A sports-scores server | **Generic search plus `read_page`** (we deleted the sports server) | A tool that only knows basketball is not a general search tool |
| 7 | Letting the model compare dates and convert time zones | **Code does it** (past-date tags, `convert_time`) | Models were 0/10 on dates. (Our own tag once mislabeled a live game as "past" because of the US/Manila date gap, so we added a day of slack.) |
| 8 | Muting the mic for the whole tool call | **Muting it only while the holding phrase plays** | A search takes 6–12 s, and during that silence you could not interrupt at all |
| 9 | Pipecat's built-in background tools | **Our own "remember and resume" observer** | With background tools on, this model started calling unrelated tools in a loop. The resume observer re-asks the cancelled question once the room is quiet |
| 10 | A fixed, loud speaker level | **A measured level plus a per-room echo check, and the volume knob by hand** | At 90 % with the knob at its old position, the agent heard itself (VAD confidence 0.66–0.93) versus 0.06–0.17 at 70–80 % |
| 11 | A more sensitive voice detector (0.65 / 0.25 s) | **Kept 0.8 / 0.35 s** | It cut the worst barge-in from 1.31 s to 0.57 s on the same clips (n=4), but its risk with music and room noise cannot be measured by the benchmark |
| 12 | A ringtone to say "ready" | **A spoken "Ready. Go ahead."** | The ringtone was hard to hear, and surprise sounds are a bad thing in front of an audience |
| 13 | Telling the agent nothing about publishing | **Saying plainly it CAN publish, and that a clear request counts as confirmation** | It refused ("tokens are unsafe") even though the tool existed. After the change it called the tool 10/10 in the eval |
| 14 | A fine-grained GitHub token for creating repos | **A short-lived classic token with only `public_repo`** | The fine-grained token returned 403 on repo creation; the classic one is the narrowest that works |
| 15 | Search with no re-ranking | **Fast depth plus a rerank step** | Median 5.8 s with deep search only versus 2.8 s with fast + rerank, with better sources |

---

## 4. The benchmark, explained

### How it was measured
The class tool **fdbench** runs on the laptop and drives the Pi's agent over a websocket. It uses **one clock** (the Pi's monotonic clock) for every stage. It plays clips (10 phrases × 3 runs plus a Full-Duplex-Bench round), and **tools are switched off** (class convention), so it measures the voice loop itself. Pi 4 8 GB, no cooling, peak 48 °C, never throttled, Wi-Fi (about 7–11 ms to the laptop). Final run: `2026-11-21_04-16-23`.

### The scores

| Metric | What it measures | Target | Mean | p95 | n | Verdict |
|---|---|---|---|---|---|---|
| **E2E latency** | End of your speech to the first audio out | < 4.0 s | **2.19 s** | 2.81 s | 30 | **Pass** |
| **ASR final** | End of speech to the final transcript | < 0.8 s | **0.31 s** | 0.34 s | 30 | **Pass** |
| **LLM first token** | Transcript to the model's first word | < 1.5 s | **1.20 s** | 1.61 s | 30 | **Pass on mean**, p95 over by 0.11 s |
| **TTS first audio** | Text to the first audio chunk | < 0.6 s | **0.41 s** | 0.36 s | 30 | **Pass** |
| **Barge-in** | You start talking to the playback stopping | < 0.8 s | **0.94 s** (n=2); re-run **0.55 s** (n=5) | 1.24 s; re-run 1.17 s | 2; 5 | **Mean passes on the re-run; the tail misses** |
| **WER** | Speech-recognition word errors | < 15 % | **9.8 %** | n/a | 30 | **Pass** |

### What the numbers mean, honestly and optimistically

- **E2E 2.19 s (p95 2.81 s).** Comfortably inside the target. It is counted from the detector's end-of-speech, so the 0.45 s end-of-speech wait is on top; a person feels about 2.6 s, still conversational. The earlier run was 2.39 s with a p95 of 4.17 s; trimming the context to the last 16 messages and switching models is what pulled the tail in.
- **ASR 0.31 s.** The streaming design shows here: the transcript is ready almost as soon as you finish.
- **LLM first token: mean 1.20 s passes, p95 1.61 s is 0.11 s over.** The honest read is that one in twenty turns is slightly slow. The optimistic read is that the p95 was 3.46 s in the earlier run, and the context trim more than halved it.
- **TTS 0.41 s.** The p95 (0.36 s) is below the mean, which just reflects a small, skewed sample. The point is that the voice starts well inside the target.
- **Barge-in: the one miss, and we know why.** The first run had only two samples (0.94 s mean). The re-run had five: mean 0.55 s, **median 0.32 s**, minimum 0.16 s, p95 1.17 s, maximum 1.31 s. We looked into the slowest trial. The agent stopped **0.02 s after it detected the interruption**; the delay was in *detecting* a softly spoken cut-in ("By the way…"). A more sensitive detector brought the worst case down to 0.57 s on the same clips (n=4), but we did not adopt it, because we cannot measure what music and room noise would do to it. So: typical interruptions stop in about a third of a second, and the tail is a detection-sensitivity trade-off that we chose deliberately.
- **WER 9.8 %.** Passes, and it is a conservative number. An earlier run measured 4.2 %. The scorer counts "20 minutes" versus "twenty minutes" and "July 4" versus "07/04" as errors, and 4 of the 30 trials were interruption clips that are cut off by design (the same clip gave the same truncated transcript 3 times out of 3, with normal ASR timing). We have strong evidence for this, but we did not inspect the clip audio itself.

### What the benchmark does not cover (and what we measured separately)
- **Tools are off in the class benchmark,** so it says nothing about search or other tool turns. Live, with tools on: a plain turn reaches the first sound in about 2–2.6 s. A tool turn says its holding phrase at about 2.4 s and, for a search, answers in a median of about **8–12 s** (the search tool alone is about 3 s; the rest is two model calls and speech). That is our slowest area, and we say so.
- **Distractor clips.** The benchmark's side-talk and TV/radio clips are meant to be ignored. In both of our runs, 5 of the 6 such clips were answered. The agent cannot yet tell speech aimed at it from speech it overhears. That is a known gap, not a graded target.

### The summary in one breath
Five of six targets pass with margin. The voice loop (hear, think, speak) is fast and stable at about 2.2 s. The one miss is the interruption tail, which we traced to a detector sensitivity trade-off and tested a fix for. The slowest part of the product is tool-heavy turns, and we measured that too, and kept improving it (parallel search, retries, progress events).

---

## 5. Known limitations and next steps
- Tool turns take a median of 8–12 s live. Next: stream partial answers, or speak while the search runs.
- Interruption tail (p95 1.17 s). Next: an adaptive detector threshold that is stricter while music plays and looser when it is quiet.
- Search can return stale pages, especially live prices and scores. The agent says "as of" and names the source, but "found" is not "correct".
- Name-only searches can find a different person. The agent says so and asks for a detail, or reads a page you name.
- A resumed search restarts from scratch rather than continuing.
- The agent cannot tell who a sentence is addressed to (see the distractor note above).
- Speech recognition sometimes mishears names or splits a sentence at a pause.

## 6. Evidence and how to reproduce
- Benchmark runs: `fd-benchmark/runs/kuya-jukebox/` (local, not committed); summary in `docs/DECK_CONTENT.md`.
- Barge-in experiment, decisions and live-run notes: `docs/STATE.md`.
- Prompt eval: `python bench/prompt_eval.py v12 v13 3`. Search health check: `python bench/search_eval.py` (no answer key). Text-only chat through the real agent: `python bench/text_chat.py "your question"`.
- Start everything: `bash scripts/start_servers.sh`, then `bash scripts/run_agent.sh`. Publishing switch: `bash scripts/demo_github.sh on|off|status`.
