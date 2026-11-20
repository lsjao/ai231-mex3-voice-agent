#!/usr/bin/env bash
# Run the voice agent (mic + speaker on the Pi). Plays the ready jingle once the agent is up. Ctrl+C to stop.
cd "$HOME/mex3" || exit 1
bash scripts/start_servers.sh
[ -f ringtone.wav ] || .venv/bin/python bench/make_ringtone.py ringtone.wav
( for i in $(seq 1 40); do grep -q "agent ready" logs/agent.log 2>/dev/null && break; sleep 1; done
  aplay -q -D plughw:Headphones ringtone.wav ) &
: > logs/agent.log
.venv/bin/python -m src.agent 2>&1 | tee -a logs/agent.log
