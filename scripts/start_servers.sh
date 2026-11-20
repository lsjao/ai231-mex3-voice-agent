#!/usr/bin/env bash
# Start our four MCP servers (asr 8101, tts 8102, weather 8103, search 8104) if they are not already listening.
# Safe to run repeatedly. Logs go to ~/mex3/logs/. Used at boot via cron @reboot and before demos.
cd "$HOME/mex3" || exit 1
mkdir -p logs
# ALSA levels reset on every reboot on this Pi: re-apply them (no sudo needed). Speaker 90%, mic 65% (100% clips).
amixer -c Headphones sset PCM 80% >/dev/null 2>&1 && echo "speaker PCM -> 80%" || echo "WARN: could not set speaker volume"
amixer -c Microphone sset Mic 65% >/dev/null 2>&1 && echo "mic gain -> 65%" || echo "WARN: could not set mic gain"
start() {  # name script port
  if ss -ltn | grep -q "127.0.0.1:$3 "; then echo "$1 already up"; return; fi
  nohup .venv/bin/python "mcp_servers/$2.py" >> "logs/$1.log" 2>&1 &
  echo "$1 started (port $3)"
}
start asr asr_mcp 8101
start tts tts_mcp 8102
start weather weather_mcp 8103
start search search_mcp 8104
start music music_mcp 8105
sleep 4
ss -ltn | grep -E ":810[1-4] " | awk '{print "listening:", $4}'
# Warm the tool servers' outbound connections in the background (first call is otherwise ~2.5 s slower).
( sleep 3; .venv/bin/python bench/warm_tools.py >> logs/warm.log 2>&1 ) &
