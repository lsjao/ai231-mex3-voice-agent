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
3 rehearsals, 2-page deck, README polish, final tag. (Backup video: DROPPED by the user. Interactive visual: being built in a SEPARATE Claude Code session from docs/VISUAL_HANDOFF.md; first-draft diagram already at docs/agent_visual.html.)

## Deliberately NOT built now: portfolio website / GitHub / GitHub Pages (instructor's sample tasks from the last demo)
Decision (user): do NOT build ahead of time; it is to be built live in the demo. Prep only, when asked:
1. User creates a public sandbox repo (e.g. `kuya-portfolio`) and a fine-grained token limited to that one repo (Contents + Pages read/write),
   saved in the `api keys` file (never in chat/repo) -> goes to ~/mex3/.env as GITHUB_PAT, with DEMO_GITHUB=1 only for the demo.
2. Plan if needed: site-builder MCP (generates a static page from details the user speaks, NOT from name-only web search, which finds strangers)
   running as a background task, plus a github MCP limited to the sandbox repo. Instructor-style demo: one big task + small tasks meanwhile + interrupt + pause.
3. Until then the agent answers honestly that it cannot do it (eval scenario `cannot_do_honest` 4/4).

## UPDATE Sat 05:05 (READ THIS FIRST; it supersedes older "Pending" lines above)
Servers on the Pi (scripts/start_servers.sh, also cron @reboot): asr 8101, tts 8102, weather 8103, search 8104, music 8105 (all 127.0.0.1),
events feed 8106 and the visual page 8107 (0.0.0.0; the page is served from ~/mex3/docs/visual, so updating the visual = `git pull` on the Pi).
Built since the sections above: music-mcp (ME2 mp3s in ~/vcm/music, default volume 65, ducking while anyone talks), fast voice path
(src/fast_commands.py: stop/pause/resume/next/previous/louder/quieter with NO LLM, ~0.4 s), echo filter, empty turns left unanswered,
person-search caution inside the search result, past-date tagging, prompt v4 in production (v5 rejected by eval), real-event log
(src/events.py -> ~/mex3/logs/sessions/*.jsonl, feeds the visual; disabled in BENCH mode).
Final benchmark (tools off, run 2026-11-21_04-16-23): E2E 2.19 s (p95 2.81), ASR 0.31, LLM TTFT 1.20 (p95 1.61), TTS 0.41, barge-in 0.94 s = MISS (n=2), WER 9.8 %. Details in docs/DECK_CONTENT.md section 5.
IN PROGRESS at 05:05: a 3-round barge-in re-measure (fdbench on the user's PC + agent in BENCH mode on the Pi), ~19 min, results in
fd-benchmark/runs/kuya-jukebox/<newest folder>/summary.md (local, git-ignored). When it finishes: put barge-in mean/p95/n into DECK_CONTENT section 5, then stop the
Pi launcher: `pkill -f "[f]d-benchmark/launch_assistant"` (run it alone, in its own ssh call).
NOT verified by a human voice session yet (the user was away for the last test): fast music commands, music audibility at volume 65, the person-search CAUTION,
empty-turn handling, and events from a LIVE run (the observer was only unit-tested with real frame objects in a temp dir).
Needs the user: (1) a free-form ~4 min rehearsal, then save that session UNEDITED as docs/visual/sample_session.json (curl http://192.168.88.8:8106/sessions, then
/replay?session=<id>) and commit ONLY that file; (2) deck format: PowerPoint copying the 2-page template layout, or only tables to paste into the professor's template; (3) demo hotspot
SSID/password if it is not the stored "Jao" (command in docs/VENUE_CHECKLIST.md); (4) only if the portfolio task is wanted: GitHub sandbox repo + fine-grained token (docs/VENUE_CHECKLIST.md section 4).
Remaining work: build the 2-page deck from docs/DECK_CONTENT.md; README polish (architecture + decision log); final tag (e.g. final-demo-v1) after one last rehearsal and echo_check in the venue;
the WER end-of-utterance clipping (2 of 30 transcripts lost the last word) is uninvestigated. Backup video was DROPPED by the user. The interactive visual is owned by a SEPARATE session (docs/visual/).
Rules learned: stage only your own paths (another session works in docs/visual/); syntax-check Python before committing (twice a broken f-string was pushed); `pkill -f` over ssh kills its own shell
(use the [x]pattern trick in a command where the name appears once); never change the user's PC settings (power plan etc.) without asking; no rehearsed or scripted agent answers anywhere; stay honest about what is unverified.

## MORNING BRIEFING (written ~05:30 Sat while the user slept)
DONE overnight: (1) barge-in re-measure finished: 5 samples, mean 0.55 s, median 0.32 s, p95 1.17 s, max 1.31 s -> mean passes the 0.8 s target, tail does not; recorded in docs/DECK_CONTENT.md section 5.
(2) Credits OK: OpenRouter $0.40 used of the key's $5 limit; Tavily 66 of 1000 searches; Deepgram key valid (balance not readable with this key; check the console). (3) WER "clipped last word" investigated:
NOT a pipeline bug: 4 of 30 trials came from two Full-Duplex-Bench interruption clips that are truncated by design (same clip -> identical truncated text 3/3, normal endpointing 0.41 s); it inflates WER. The audio itself was not inspected.
(4) README.md rewritten (architecture, MCP table, honest results, decision log, how to run). (5) Pi launcher for the benchmark stopped; no stray sessions in ~/mex3/logs/sessions (0).
STILL UNVERIFIED by a human voice session: fast music commands, music audibility at volume 65, person-search CAUTION, empty-turn handling, events from a LIVE run, ringtone audibility for the user.
NEEDS THE USER (in this order): free-form ~4 min rehearsal (say "ready") -> save /replay of that session UNEDITED as docs/visual/sample_session.json and commit only that file; deck format answer
(default if no answer: editable PowerPoint copying the 2-page template layout, built from docs/DECK_CONTENT.md); demo hotspot SSID/password if not the stored "Jao"; GitHub sandbox repo + token only if the portfolio task is wanted.
Then: build the 2-page deck, run echo_check.sh in the venue, final tag (e.g. final-demo-v1).

## UPDATE Sat 08:45 (after the first real free-form rehearsal)
Real session saved UNEDITED as docs/visual/sample_session.json (217 events, 22 turns, from /replay of session 20261121-083140). Silent-start rehearsal works (spoken "Ready. Go ahead." via bench/say.py, NO ringtone: the user never wanted surprise sounds).
Findings from that rehearsal: no phantom turns or self-hearing (all 22 transcripts were real speech); person-search caution worked (no stranger facts); search turns still 8-9 s end to end; NBA "next game/schedule" questions failed
because schedule queries went to the news-only search filter; the agent did not know the clock (asked the user for the time zone); election answers had no sources (the NY "41-22" result may be stale 2024 data labelled 2026: unverified).
FIXES deployed on the Pi (not yet verified by voice): sports-mcp :8108 (ESPN scoreboard JSON: nba_games(when), nba_next_games(), times in Asia/Manila), get_current_time in weather-mcp,
schedule words (next game/schedule/upcoming/when is...) use general search with no news filter, search results end with "Sources: <outlets>". Agent registers sports-mcp (src/agent.py TASK_SERVERS) and start_servers.sh starts it.
NOT yet tried by voice: music commands (the user did not ask for music this time), the new NBA/time tools, "give me a source". Next: a short voice test of those, then the deck (default PowerPoint) and final tag.
