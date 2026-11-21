#!/usr/bin/env bash
# Run the voice agent (mic + speaker on the Pi). When the agent is up it says "Ready. Go ahead." out loud (no ringtone);
# the live visual switches to LIVE at the same moment, because the agent logs its first event when it is ready. Ctrl+C to stop.
cd "$HOME/mex3" || exit 1
bash scripts/start_servers.sh
( for i in $(seq 1 40); do grep -q "agent ready" logs/agent.log 2>/dev/null && break; sleep 1; done
  sleep 1; .venv/bin/python bench/say.py "Ready. Go ahead." >/dev/null 2>&1 ) &
: > logs/agent.log
.venv/bin/python -m src.agent 2>&1 | tee -a logs/agent.log
