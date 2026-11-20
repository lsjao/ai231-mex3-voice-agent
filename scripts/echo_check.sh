#!/usr/bin/env bash
# Venue field check (about 1 minute): plays the agent's own voice at several speaker volumes while you stay SILENT,
# and reports which volumes the mic + VAD hear as speech. Use the loudest volume marked SAFE. Run it in the demo room,
# with the fan/noise on and the mic and speaker where they will sit.
#   Usage: bash scripts/echo_check.sh        (servers must be up: bash scripts/start_servers.sh)
cd "$HOME/mex3" || exit 1
.venv/bin/python bench/tts_sample.py tts_sample.wav >/dev/null 2>&1 || { echo "tts server not up"; exit 1; }
echo "Stay SILENT for about 50 seconds while the agent's voice plays at different volumes..."
best=""
for vol in 90 85 80 75 70 65; do
  amixer -c Headphones sset PCM ${vol}% >/dev/null 2>&1
  (sleep 1; aplay -q -D plughw:Headphones tts_sample.wav) &
  out=$(.venv/bin/python bench/mic_path_test.py 9 2>&1 | grep "REAL VAD")
  wait
  conf=$(echo "$out" | sed -E 's/.*best confidence ([0-9.]+);.*/\1/')
  trig=$(echo "$out" | grep -c "YES")
  if [ "$trig" = "0" ] && awk "BEGIN{exit !($conf < 0.35)}"; then verdict="SAFE"; [ -z "$best" ] && best=$vol; else verdict="RISKY (self-interrupt)"; fi
  echo "speaker ${vol}%: echo confidence ${conf}  ->  ${verdict}"
done
if [ -n "$best" ]; then amixer -c Headphones sset PCM ${best}% >/dev/null 2>&1; echo "$best" > "$HOME/mex3/.speaker_pct"; echo "Set speaker to ${best}% (loudest safe level) and saved it for reboots."
else amixer -c Headphones sset PCM 65% >/dev/null 2>&1; echo 65 > "$HOME/mex3/.speaker_pct"; echo "No safe level found: set to 65%. Move the mic away from the speaker or use a headset."; fi
