#!/usr/bin/env bash
# Start everything the demo needs, if not already listening: our five MCP servers (asr 8101, tts 8102, weather 8103,
# search 8104, music 8105), the events feed for the live visual (8106) and the visual's web page itself (8107).
# Safe to run repeatedly. Logs go to ~/mex3/logs/. Used at boot via cron @reboot and before demos.
cd "$HOME/mex3" || exit 1
mkdir -p logs
# ALSA levels reset on every reboot on this Pi: re-apply them (no sudo needed). Mic 65% (100% clips).
VOL=$(cat "$HOME/mex3/.speaker_pct" 2>/dev/null || echo 80)   # the venue echo_check.sh stores its chosen level here
amixer -c Headphones sset PCM ${VOL}% >/dev/null 2>&1 && echo "speaker PCM -> ${VOL}%" || echo "WARN: could not set speaker volume"
amixer -c Microphone sset Mic 65% >/dev/null 2>&1 && echo "mic gain -> 65%" || echo "WARN: could not set mic gain"
start() {  # name script port   (MCP servers, localhost only)
  if ss -ltn | grep -q "127.0.0.1:$3 "; then echo "$1 already up"; return; fi
  nohup .venv/bin/python "mcp_servers/$2.py" >> "logs/$1.log" 2>&1 &
  echo "$1 started (port $3)"
}
start_any() {  # name port command...   (helpers that listen on all interfaces so the laptop can reach them)
  if ss -ltn | grep -q ":$2 "; then echo "$1 already up"; return; fi
  nohup "${@:3}" >> "logs/$1.log" 2>&1 &
  echo "$1 started (port $2)"
}
start asr asr_mcp 8101
start tts tts_mcp 8102
start weather weather_mcp 8103
start search search_mcp 8104
start music music_mcp 8105
start sports sports_mcp 8108
start_any events 8106 .venv/bin/python scripts/events_server.py
if [ -d "$HOME/mex3/docs/visual" ]; then
  start_any visual 8107 python3 -m http.server 8107 --directory "$HOME/mex3/docs/visual"
else
  echo "visual: docs/visual not on the Pi yet (git pull in ~/mex3)"
fi
sleep 4
ss -ltn | grep -E ":810[1-7] " | awk '{print "listening:", $4}' | sort
# Warm the tool servers' outbound connections in the background (first call is otherwise ~2.5 s slower).
( sleep 3; .venv/bin/python bench/warm_tools.py >> logs/warm.log 2>&1 ) &
