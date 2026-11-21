# HANDOFF: build the "Kuya Jukebox" live visual (separate Claude Code session)

You are a fresh session. Read `docs/STATE.md` first (system overview, ports, gotchas), then `docs/DECK_CONTENT.md` (numbers and the story).
Repo: github.com/lsjao/ai231-mex3-voice-agent. Deadline for the whole project: Sat 2026-11-21 13:59 (Asia/Manila). The user is asleep or busy: decide small things yourself, ask only about big ones.

## What to build
One self-contained web page (HTML + CSS + vanilla JS, no build step, **works fully offline**) that is **projected during the live demo** of a voice agent.
Put your work ONLY in `docs/visual/` (e.g. `docs/visual/index.html`). Do NOT touch `src/`, `mcp_servers/`, `scripts/`, `prompts/`: another session owns the frozen pipeline.
A rough technical-diagram version already exists at `docs/agent_visual.html` (clickable component map with scenario animations). Reuse its content (component facts, measured numbers, problem-and-fix text) or its ideas, but the new page is a branded "jukebox console", not a diagram.

## Must have
1. **Jukebox hero** (see the reference photo the user showed: a neon jukebox with an amber/coral arch, cream tubes, cyan and pink glass panels, on a deep dark-red background). Draw it as CSS/SVG (do not embed the photo). It shows the agent's STATE with motion: idle (slow glow), listening (arch pulses with a waveform ring), thinking (record/dial slowly spins), speaking (equalizer bars on the glass panels), tool call (a small light chases around the arch), music playing (panels cycle colors), barge-in (quick flash then settle).
2. **Chat panel (live mirror)**: shows the REAL conversation as it happens: what the user said (ASR transcript), what the agent said, tool calls ("get_weather", "web_search", "music_play"), interruptions, and the slow-connection line when it fires. Each turn shows its own latency chips: ASR final, LLM first token, TTS first audio, end-to-end.
3. **Critical metrics** (big, readable from the back of a room): (a) per-turn live latency (above), (b) **benchmark vs targets** with a clear pass/miss for E2E 4.0 s, ASR final 0.8 s, LLM first token 1.5 s, TTS first audio 0.6 s, barge-in 0.8 s, WER 15 %; (c) **robustness numbers** (the speaker volume cliff: agent's own voice scores VAD confidence 0.17 at 80 % volume vs 0.9 at 90 %; fan alone 0.05; zero phantom turns in the live run with fan on).
4. A small "before and after" strip is welcome but optional (WER 21 % to 4 %, ASR final 2.6 s to 0.3 s, past-date eval 0/10 to 10/10).

## HARD RULE: no rehearsed or scripted content
The chat must never show written-in or rehearsed answers. Only two sources are allowed:
- **LIVE**: events streamed from the Pi (contract below).
- **REPLAY**: a recording of a *real past session* captured from the agent's own event log (`docs/visual/sample_session.json`, produced from a real rehearsal, not authored). When showing it, display a clear badge "REPLAY of a recorded real session, <date>" and never mix it into live view.
If neither is available, show an honest empty state ("waiting for the agent"), not fake messages. All numbers on screen must come from real runs and carry their label (benchmark = tools off; live tool turns are slower and shown separately).

## Live data contract (Pi side is being built by the other session; ETA before the user wakes)
- Server on the Pi: `http://192.168.88.8:8106` (the Pi's IP may change; make the host editable in the page and remember it in localStorage).
- `GET /events` : Server-Sent Events stream of JSON objects, one per line, CORS open.
- `GET /sessions` : list of recorded sessions; `GET /replay?session=<id>` : that session's events as JSON array.
- Event shapes (all have `t` = seconds on the Pi's monotonic clock, `session`, `turn` number):
  `{"type":"state","state":"idle|listening|thinking|speaking|tool|music"}`
  `{"type":"user","text":"...","asr_ms":320}`            // final transcript and ms from end-of-speech to transcript
  `{"type":"agent","text":"...","llm_ms":1250,"tts_ms":380,"e2e_ms":2210}`
  `{"type":"tool","name":"get_weather","phase":"start|end","ms":900}`
  `{"type":"interrupt"}` `{"type":"guard","line":"slow-connection line spoken"}` `{"type":"echo_dropped","text":"..."}` `{"type":"music","action":"play|pause|stop|duck","title":"..."}`
- If this endpoint is not up yet when you start, build against a small local mock **that generates events from random timings only for layout testing, clearly flagged DEV MOCK and removed from the final file**. The final page must not ship with mock text.
- Connection UI: a small status pill (LIVE / RECONNECTING / REPLAY / WAITING). Auto-reconnect. Never block rendering on the network.

## Design
- **Font: Google Sans** (open-sourced by Google in late 2025, reportedly under the SIL Open Font License; **verify the license file in the Google Fonts GitHub repo before using**, and self-host the .woff2 files next to the page so it works offline). Fallback stack: `"Google Sans", "Google Sans Flex", system-ui, "Segoe UI", sans-serif`. `font-display: swap`. If Google Sans cannot be self-hosted legitimately, use the fallback and tell the user.
- **Palette: soft neon on deep wine**, taken from the jukebox photo but softened so text is comfortable:
  background `#160709` to `#2a0d12` (subtle radial glow behind the hero); surface `#241016`; text cream `#fdf1e3`, muted `#c9a99b`;
  accents: amber `#ffc15e`, coral `#ff7a66`, soft red `#ff4d5e` (large shapes only, never small body text), cyan `#7fe3f0`, pink `#ff8ad8`; good `#8de8b8`, miss `#ff9b8a`.
  Keep body text contrast >= 7:1; accents on small text >= 4.5:1; never rely on color alone for pass/miss (add an icon or word).
- **Motion**: CSS animations only (transform/opacity/filter), subtle and purposeful; respect `prefers-reduced-motion` (replace pulses with static states). No audio, no autoplay sound, no heavy canvas loops.
- **Projector readability**: key numbers >= 28 px, chat text >= 20 px, dark theme default, optional high-contrast toggle. Layout for 16:9 at 1280x720 and 1920x1080; also usable on a laptop. Keyboard accessible; labels for the status pill and metrics.

## Facts to show (verified; benchmark was tools OFF per the class convention)
Final benchmark numbers will be in `fd-benchmark/runs/kuya-jukebox/2026-11-21_04-16-23/summary.md` (local only, git-ignored) and copied into `docs/DECK_CONTENT.md` by the other session. Until then use the earlier run: E2E 2.39 s (p95 4.17), ASR final 0.26 s, LLM first token 1.51 s (p95 3.46), TTS first audio 0.41 s, barge-in 0.59 s (n=2), WER 4.2 %.
Live tool turns (tools ON, not in the benchmark): plain turn ~2.0 to 2.6 s; search turn: holding phrase ~2.4 s, full answer ~5 to 8 s.
Pipeline: USB mic -> Silero VAD + Smart Turn -> asr-mcp (Deepgram streaming) -> LLM (OpenRouter gpt-4.1-mini) -> tts-mcp (Deepgram Aura-2) -> speaker; task MCP servers weather, search, music (all ours, on the Pi). Name: Kuya Jukebox (male, English-only).

## Done means
Open `docs/visual/index.html` from disk with Wi-Fi off: hero animates through all states using the REPLAY source; with the Pi reachable it switches to LIVE; metrics panel and robustness panel render; no external requests (check the network tab); no console errors; works at 1280x720 and 1920x1080; reduced-motion honored. Commit only under `docs/visual/` (no keys, no mp3, no secrets) and tell the user what you verified and what you could not.

## NEW (Sat 2026-11-21 ~12:45): `task` events for a progress indicator on the left side of the jukebox
The agent now emits `{"type":"task", ...}` lines on the same SSE feed (:8106) and in the session JSONL, one per slow tool call (search, page read, site build). Fields:
- `id` (the tool call id), `name` (`web_search` | `read_page` | `publish_website`), `label` (a ready-to-show string: "Searching the web", "Reading a page", "Building your page"),
- `status`: `running` (emitted at start and again every ~3 s as a heartbeat, with `elapsed_ms`), `done` (with `elapsed_ms`), `cancelled` (the user interrupted it), `resumed` (the agent is picking the interrupted request back up; no id).
Suggested UI: a small pill on the left of the jukebox while any task is `running`, showing `label` and a ticking `elapsed_ms`; clear it on `done`/`cancelled`; a brief "back to it" flash on `resumed`.
The existing `tool` start/end events are unchanged. Nothing in `docs/visual/` was edited for this.
