# Venue checklist (different Wi-Fi / phone hotspot, open room)

## 1. Network: the Pi must join the venue hotspot by itself
- The Pi already stores two Wi-Fi profiles, both auto-connect: `WOOFY_812A4D_2.4G` (home) and `Jao` (probably the phone hotspot). If the demo hotspot is named `Jao`
  with the same password, nothing to do.
- Phone hotspot settings: iPhone -> Personal Hotspot -> **Maximize Compatibility ON** (2.4 GHz); Android -> 2.4 GHz band. Keep the phone plugged in, screen awake,
  and test the whole pipeline over it for 20+ minutes beforehand. The venue's own Wi-Fi was unreliable last time (a classmate's Pi saw "invalid SSID").
- To store a NEW network without joining it right now (so the Pi does not leave home Wi-Fi and break your SSH), run in your own terminal on the Pi
  (needs the Pi password; put a space before the command so it stays out of shell history):
  `sudo nmcli connection add type wifi con-name venue ifname wlan0 ssid "<SSID>" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "<PASSWORD>" connection.autoconnect yes connection.autoconnect-priority -10`
  Lower priority = home Wi-Fi wins at home; at the venue (home absent) the Pi joins `venue`.
- Reach the Pi on any network: put the laptop on the SAME hotspot, then `ssh rpi-local` (alias for rpi-jao.local, works via mDNS) instead of the home IP.
- The agent only needs the internet, not your laptop. The laptop is only for SSH, the class benchmark and the live visual (Pi event feed: port 8106, when built).

## 2. Sound in an open room (echo vs loudness)
- The Pi's speaker level is **90 %** (saved in `~/mex3/.speaker_pct`, re-applied at every start). The physical speaker knob is maxed, so **lower the knob by hand** at the venue until the room sounds right.
  Why: the agent's own voice scored 0.06-0.17 VAD confidence at 70-80 %, ~0.4 at 85 %, 0.66-0.93 at 90 % (self-interrupts) when measured with the knob at its earlier position, so the knob is the safety valve.
- Run `bash ~/mex3/scripts/echo_check.sh` IN THE ROOM, with the mic and speaker where they will sit; stay silent ~1 min (it plays the agent voice at six levels). It picks the loudest safe level and saves it.
  If it picks a lower level than 90 %, trust it.
- More room volume safely: mic close to your mouth (10 cm vs 40 cm is ~12 dB), speaker aimed at the audience, more distance between them (6 dB per doubling). A headset or clip-on mic is ideal.
  Music has its own volume (default 65) and ducks while anyone talks.
- If the agent interrupts itself: lower the knob first, then re-run the echo check. The sensitive VAD setting (0.65 / 0.25 s) is NOT adopted; see docs/STATE.md.

## 3. Before the demo (15 minutes)
1. Power: Pi on a reliable supply, spare cable. 2. Hotspot on, laptop joined, `ssh rpi-local`.
3. `bash ~/mex3/scripts/start_servers.sh` (idempotent; should show 8 "listening" lines) and `python bench/check_keys.py` (credits).
4. `bash ~/mex3/scripts/echo_check.sh`.
5. `bash ~/mex3/scripts/run_agent.sh` (it says "Ready. Go ahead." out loud; the visual flips to LIVE at the same moment). Or use `docs/visual/demo.ps1` from the laptop.
6. One free-form warm-up question, one weather question, one "play some focus music" / "stop the music", and one search you interrupt with a quick question (it should answer, then return to the search). Then the real demo.
Voice commands that work with NO LLM delay (~1.2 s including the spoken acknowledgement): "stop / pause / resume the music", "next / previous song", "louder / quieter".

## 4. GitHub Pages website task (ready; switched off until you say so)
- Sandbox repo: `lsjao/kuya-portfolio` (public, Pages on from `main` root, placeholder "Coming soon" page). Site: https://lsjao.github.io/kuya-portfolio/ . A push appears after ~30-60 s.
- Token: fine-grained, that one repo only, Contents read/write, **expires 2026-12-21**, stored on the Pi in `.env` as `GITHUB_PAT` (mode 600). Write-tested: the sandbox repo accepts writes, other repos return 403. A test file was added and removed (two commits in history).
- Switch it on right before the demo and off right after: `bash ~/mex3/scripts/demo_github.sh on` / `off` / `status`. With it off, the agent builds a preview on the Pi and says nothing went online.
- Flow: the agent searches (or reads a profile page you name, e.g. github.com/<handle>), then asks you to confirm, then builds and publishes. Name-only searches can find a different person; give it a detail or a page address.
  The generated page is sanitised (no scripts or external resources) and carries an "unverified, drafted from public search results" footer. The page it publishes replaces the placeholder `index.html`.
- To restore the placeholder afterwards, re-add the "Coming soon" page via the GitHub web UI (the previous version is in the repo history).
