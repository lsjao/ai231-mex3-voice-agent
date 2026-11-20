#!/usr/bin/env bash
# Phase 0 audio check: list devices, record 5s from USB mic, play on Headphones, show PCM.
set -euo pipefail
arecord -l; aplay -l
MIC="${MIC:-plughw:CARD=Device,DEV=0}"   # override: MIC=plughw:1,0 ./audio_check.sh
arecord -D "$MIC" -f S16_LE -r 16000 -c 1 -d 5 "$HOME/mex3/test.wav"
aplay -D plughw:Headphones "$HOME/mex3/test.wav"
amixer -c Headphones sget PCM
