# MEX3 state handoff (for a fresh session or a teammate)

Deadline: Sat 2026-11-21 13:59. Repo: github.com/lsjao/ai231-mex3-voice-agent. Rollback tag: `rollback-bench-v1`.

## What it is
Full-duplex voice agent "Kuya Jukebox" on a Raspberry Pi 4 (8 GB, host `rpi-jao`, user `jaolacuata`, IP 192.168.88.8, ssh alias `rpi`).
Pipecat 1.16 pipeline: USB mic -> Silero VAD (+ Smart Turn v3) -> our asr-mcp (Deepgram nova-3 streaming) -> LLM
(openai/gpt-4.1-mini via OpenRouter) -> our tts-mcp (Deepgram Aura-2 Orion) -> 3.5 mm speaker. Barge-in cancels TTS + LLM.

## Our MCP servers (all on the Pi, localhost, streamable HTTP; started at boot by cron @reboot -> scripts/start_servers.sh)
asr 8101 (asr_start/asr_push/asr_finish) | tts 8102 (speak_start/speak_next/speak_cancel/tts_warm) | weather 8103 (Open-Meteo) |
search 8104 (Tavily, recency-biased, tags past dates) | [planned] music 8105 (ME2 local mp3 playlists in ~/vcm/music).

## Run / operate
- `ssh rpi` then `bash ~/mex3/scripts/start_servers.sh` (idempotent; also sets speaker 80% / mic 65%).
- Agent: `bash ~/mex3/scripts/run_agent.sh` (plays ringtone when ready). Logs: ~/mex3/logs/.
- Venue echo check (stay silent ~1 min): `bash ~/mex3/scripts/echo_check.sh`  (agent voice at speaker >=90% self-interrupts).
- Pre-demo key/credit check: `python bench/check_keys.py`. Keys live ONLY in ~/mex3/.env on the Pi (never commit).
- Benchmark (class tool "fdbench"): laptop `fd-benchmark/` runs it, Pi runs `fd-benchmark/launch_assistant.py` (BENCH=1, tools off).

## Key files
src/agent.py (pipeline, build() entry for fdbench) | src/mcp_services.py (STT/TTS services calling our MCP servers) |
src/guard.py (context trim, slow-API line) | src/echo.py (drops transcripts that echo the agent's own speech) |
prompts/system_v1..v5.md (production = v4; v5 regressed in eval, not adopted) | bench/prompt_eval.py (LLM-judge eval) |
docs/PLAN.md, README.md.

## Decisions and evidence (for the deck)
Pipecat harness; Deepgram ASR+TTS wrapped by our own MCP servers; ASR streaming because the Pi is ~236 ms RTT from Deepgram.
Benchmark (tools off): E2E ~2.4 s, ASR final ~0.3 s, TTS first audio ~0.4 s, WER 4.2 %, barge-in ~0.6 s (n=2). Tool turns 5-8 s.
Found-and-fixed: first words clipped (WER 21 %->4 %), TTS replies one turn late, speaker 90 % self-interrupt cliff, model compares dates badly
(fixed in code), name-only person search returns strangers (guard in tool description).

## Gotchas
- Pi `sudo` needs the account password (ask the user). `pkill -f` over ssh can kill its own shell: stop and start in separate calls.
- ALSA volumes reset on reboot (start_servers.sh re-applies them). Python 3.13 venv at ~/mex3/.venv.
- Do not commit: .env, `api keys` file, music/*.mp3 (copyrighted ME2 tracks), fd-benchmark/ (separate repo).
- Syntax-check every Python file before committing (twice a broken f-string was pushed).

## Pending (as of 04:35 Sat)
Final benchmark re-run (in progress), music MCP (ME2 carry-over: the user asked repeatedly; "Kuya Jukebox" was their ME2 music player),
3 rehearsals, backup video, 2-page deck, interactive HTML component diagram, README polish, final tag.

## Deliberately NOT built now: portfolio website / GitHub / GitHub Pages (instructor's sample tasks from the last demo)
Decision (user): do NOT build ahead of time; it is to be built live in the demo. Prep only, when asked:
1. User creates a public sandbox repo (e.g. `kuya-portfolio`) and a fine-grained token limited to that one repo (Contents + Pages read/write),
   saved in the `api keys` file (never in chat/repo) -> goes to ~/mex3/.env as GITHUB_PAT, with DEMO_GITHUB=1 only for the demo.
2. Plan if needed: site-builder MCP (generates a static page from details the user speaks, NOT from name-only web search, which finds strangers)
   running as a background task, plus a github MCP limited to the sandbox repo. Instructor-style demo: one big task + small tasks meanwhile + interrupt + pause.
3. Until then the agent answers honestly that it cannot do it (eval scenario `cannot_do_honest` 4/4).
