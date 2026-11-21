# Kuya Jukebox live visual

Open `index.html` (works offline; no build step, no external requests).

- **LIVE**: connects to `http://<Pi host>/events` (default `192.168.88.8:8106`, editable in the header, remembered in localStorage).
- **Animation preview** (state picker on the jukebox): shown until the first real event arrives; hero states only, never conversation text. Motion is always on.
- No scripted or sample conversation ships in this folder. The page shows the live conversation (per-turn latency chips, no pass/miss tags) (benchmark and robustness numbers live in the deck, not here; the earlier Numbers view and Replay were removed, tag `visual-v1` has them).

Font: Google Sans (SIL OFL 1.1, `fonts/OFL.txt`, copyright Google Sans Project Authors), Latin subset, variable weight 400-700.
