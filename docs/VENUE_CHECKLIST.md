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
- The speaker level is limited by echo: agent voice heard by the mic scored 0.06-0.17 VAD confidence at 70-80 %, ~0.4 at 85 %, 0.66-0.93 at 90 % (self-interrupts).
- Run `bash ~/mex3/scripts/echo_check.sh` IN THE ROOM, with the mic and speaker where they will sit; stay silent ~1 min. It picks the loudest safe level and saves it for reboots.
- Get more room volume safely by raising your voice relative to the speaker at the mic: mic close to your mouth (10 cm vs 40 cm is ~12 dB), mic back toward the speaker,
  speaker aimed at the audience, more distance between them (6 dB per doubling). A headset or clip-on mic is ideal. Music has its own volume (default 65) and ducks while anyone talks.

## 3. Before the demo (15 minutes)
1. Power: Pi on a reliable supply, spare cable, spare SD card idea (a re-flash takes ~45 min). 2. Hotspot on, laptop joined, `ssh rpi-local`.
3. `bash ~/mex3/scripts/start_servers.sh` (idempotent) and `python bench/check_keys.py` (credits). 4. `bash ~/mex3/scripts/echo_check.sh`.
5. `bash ~/mex3/scripts/run_agent.sh` (ringtone = ready). 6. One free-form warm-up question, one weather question, one "play some focus music" / "stop the music".
Voice commands that work with NO LLM delay (~0.4 s): "stop / pause / resume the music", "next / previous song", "louder / quieter".

## 4. GitHub (only if the instructor asks for the portfolio/site task live; nothing is built ahead of time)
What I need from you, in advance, saved in your local `api keys` file (never in chat or the repo):
1. A **public sandbox repo** under your account (suggested name `kuya-portfolio`) with **Pages enabled** (Settings -> Pages -> deploy from the `main` branch, root). Tell me `owner/repo`.
2. A **fine-grained personal access token** limited to THAT ONE repo: Contents = Read and write, Pages = Read and write (Metadata read is automatic). Short expiry (3-7 days).
   It goes to `~/mex3/.env` as `GITHUB_PAT`, with `DEMO_GITHUB=0` until the demo.
3. For the portfolio content: your name as it should appear, school/program, 2-4 projects (one line each), links you want shown, and a photo path if any.
   The agent builds the page from what you SAY and these details, not from a name-only web search (that finds strangers).
When you hand over the token I will only run read-only checks (token valid, repo reachable, Pages status) and report; I will not push anything until you say so.
Planned design if needed: a site-builder step writes static HTML on the Pi, then a github tool uploads it through the GitHub REST API (no git credentials on the Pi), limited to the sandbox repo.
