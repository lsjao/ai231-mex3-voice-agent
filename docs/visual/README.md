# Kuya Jukebox live visual

Open `index.html` (works offline; no build step, no external requests).

- **LIVE**: connects to `http://<Pi host>/events` (default `192.168.88.8:8106`, editable in the header, remembered in localStorage).
- **REPLAY**: only a recording of a real session. Header menu > Replay: pick a file, or list sessions on the Pi.
  To keep one next to the page: `curl "http://192.168.88.8:8106/replay?session=<id>" > docs/visual/sample_session.json`
  (when the page is opened from disk the browser cannot read it by itself; use "Choose a recorded session file").
- **Animation preview**: shows hero states only, never any conversation text.
- No scripted or sample conversation ships in this folder. Benchmark/robustness numbers are in the `BENCH`, `ROBUST`, `BEFORE_AFTER`, `TOOLS_ON` constants at the top of the script, each with its source label.

Font: Google Sans (SIL OFL 1.1, `fonts/OFL.txt`, copyright Google Sans Project Authors), Latin subset, variable weight 400-700.
