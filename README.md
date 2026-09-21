# Rocket League Stats Suite

Three tools for Rocket League players and creators, all built on one shared core
that reads the game's local **Stats API** WebSocket:

1. **Personal Stats Tracker** — records every match to SQLite and shows trends on a Flask dashboard.
2. **Stream Alert App** — fires custom audio/visual alerts to an OBS browser-source overlay.
3. **Goal Highlight Auto-Editor** — syncs goal timings to your recording and cuts a highlight reel with ffmpeg.

Everything runs against a **mock Stats API server** too, so you can develop, test
and demo the whole suite without Rocket League running.

---

## How the Stats API works

Rocket League ships a client-side WebSocket that streams live match data from
your own machine. Enable it once:

1. Open `<Rocket League Install>\TAGame\Config\DefaultStatsAPI.ini`.
2. Set `PacketSendRate` to a value above `0` (e.g. `10`).
3. Launch the game. The socket listens on `ws://localhost:49123`.

It's **real-time only** — it never touches recorded video or past matches. It
emits JSON messages of the form `{ "Event": "...", "Data": { ... } }`. The
events and their payloads are documented in [`rlstats/events.py`](rlstats/events.py).

---

## Setup

Requires **Python 3.10+**. (Developed on 3.13.)

```bat
cd rl-stats-suite
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

`ffmpeg` is only needed for Tool 3 (highlights). Install it separately and make
sure it's on your PATH:

```bat
winget install Gyan.FFmpeg
```

Optional: `copy config.example.json config.json` and edit it (player name, ports,
etc.). Anything you leave out falls back to the defaults in
[`rlstats/config.py`](rlstats/config.py).

---

## Quick start (no game required)

Everything is driven through one launcher, `rl.py`:

```bat
:: Simulate a match and record it, then open the dashboard — one command:
python rl.py demo

:: Or fill the dashboard with demo data instantly:
python rl.py seed --matches 40
python rl.py dashboard
```

To use it with the real game, just start the relevant tool while RL is running
with the Stats API enabled (no mock needed).

---

## Tool 1 — Personal Stats Tracker

```bat
python rl.py track        :: background recorder: writes each finished match to SQLite
python rl.py dashboard    :: open http://127.0.0.1:5000
```

- The recorder ([`tracker/recorder.py`](tracker/recorder.py)) listens for
  `MatchEnded`, builds a per-player snapshot, accumulates boost usage from the
  live ticks, and writes one match + per-player rows to SQLite
  ([`tracker/db.py`](tracker/db.py)).
- The dashboard ([`tracker/dashboard.py`](tracker/dashboard.py)) renders win
  rate over time, saves per game, performance by arena, session summaries, and a
  recent-matches table (Chart.js).

Try it with the mock in two terminals:

```bat
python rl.py mock           :: terminal 1 (loops matches forever)
python rl.py track          :: terminal 2
python rl.py dashboard      :: terminal 3
```

---

## Sharing the tracker with others (standalone .exe)

Non-technical people don't need Python, the terminal, or this repo — just one file.

**Build it** (on a machine with the project set up):

```bat
build_exe.bat          :: or: python rl.py ... see the file
```

This produces a single **`dist\RLStatsTracker.exe`**. Send that file to anyone.

**What they do:** double-click `RLStatsTracker.exe`. It will:
1. find Rocket League and turn on its Stats API for them,
2. record every real match in the background (freeplay/training ignored),
3. open the stats dashboard in their browser.

They keep the window open while playing and close it to stop. Their database
(`data\matches.db`) is created next to the .exe, so stats persist.

> First-run note: if their Rocket League is under `Program Files` and the API
> isn't enabled yet, enabling it needs admin once — the app says so; they
> right-click → **Run as administrator** a single time, then run normally.
> You can also enable it manually any time with `python rl.py setup-api`.

### Background-only launchers (this machine)

If you've got the project set up, these double-click `.bat` files skip the
terminal too: **`Start Tracker.bat`**, **`Open Dashboard.bat`**,
**`Watch Live Events.bat`**.

---

## Real matches only (freeplay is ignored)

The Stats API streams in *every* game state, including freeplay and training.
The suite records a goal/match only when it's a **real match** — detected by
opponents being present on a second team, plus a playlist that isn't
freeplay/training (configurable via `ignore_playlists`). This keeps practice
shots out of your highlight reels and junk out of your stats.

See exactly what your game sends, and how each event is classified, with:

```bat
python rl.py monitor --show-state
```

Goals show `[WOULD TRACK]` in a real match and `[ignored: not a real match]`
in freeplay — handy for confirming/tuning the filter against your install.

---

## Tool 2 — Stream Alert App

```bat
python rl.py alerts
```

This prints two URLs. In **OBS**, add a **Browser source** pointing at the
overlay page (e.g. `http://127.0.0.1:8080/?hud=0`) over your game capture. The
overlay connects back to the push socket automatically and animates alerts as
events fire.

- Rules live in `alerts/rules.json` (copy [`alerts/rules.example.json`](alerts/rules.example.json)).
  Each rule maps an event + conditions to an alert (title, subtitle, icon,
  color, animation, sound). See the header of [`alerts/rules.py`](alerts/rules.py)
  for the full schema and the available built-in (synthesized) sounds.
- Preview the overlay's look without the game:
  `http://127.0.0.1:8080/?demo=1` cycles sample alerts.

Example rule:

```json
{
  "name": "Screamer",
  "event": "GoalScored",
  "when": { "scored_by_me": true, "goal_speed": { ">=": 100 } },
  "alert": { "title": "WHAT A SCREAMER!", "subtitle": "{goal_speed} kph rocket",
             "icon": "🚀", "color": "#ff8b32", "animation": "flash", "sound": "airhorn" }
}
```

---

## Tool 3 — Goal Highlight Auto-Editor

The Stats API knows *when* goals happen but knows nothing about your video, so we
sync two clocks with a single reference point:

```
recording_start = system clock when recording starts   (the video's t=0)
goal position   = goal_event_time − recording_start
```

### Recommended: cut from your own recording (`hl-log` + `hl-cut`)

Record however you already do (**OBS, NVIDIA ShadowPlay, Xbox Game Bar** — best
quality, handles fullscreen + audio). We only log the goal times and cut. No
screen capture by us, so none of the fullscreen/borderless/audio gotchas.

```bat
python rl.py hl-log              :: run this while you play (logs goal times)
:: ...record your match in OBS/ShadowPlay as usual, then:
python rl.py hl-cut "C:\Videos\match.mp4"      :: auto-matches goals + cuts the reel
python rl.py hl-cut match.mp4 --dry-run        :: preview the plan
python rl.py hl-cut match.mp4 --offset -1.5    :: nudge if timing is slightly off
```

It reads the video's start time from its `creation_time` metadata and matches
the goals you logged by their timestamps — fully automatic, works with any
recorder. Output: `<video>_reel.mp4`.

### Alternative: let the tool record your screen (`hl-auto`)

The tool records your screen itself, so the video's t=0 and the goal clock are
the same instant. When the match ends it auto-cuts the reel. **Requires Rocket
League in borderless/windowed** (exclusive fullscreen captures black/frozen).

```bat
python rl.py hl-auto                 :: or double-click "Auto Highlights.bat"
python rl.py hl-auto --pre 6 --post 4
python rl.py hl-auto --desktop       :: capture whole desktop instead of the game window
```

- Captures only the Rocket League window by default (set `highlight_capture_window`).
  **Run RL in borderless/windowed** — exclusive fullscreen can capture black.
- Output: `data/recordings/match_<ts>.mkv` (full video) and `..._reel.mp4` (the reel).
- If clips land slightly early/late, tune `highlight_capture_sync_offset` in config
  (more negative = earlier) or pass `--offset` to a manual `hl-build`.
- Real-time only: it can't find goals in footage recorded before the tool was running.

### Manual: sync to your own OBS recording (`hl-record` + `hl-build`)

**Start the session at the same moment you start your OBS/screen recording:**

```bat
python rl.py hl-record --start --video "D:\clips\match.mkv"
```

Leave it running; each goal is logged and the session file is saved live. Stop
with `Ctrl+C`, then build the reel:

```bat
python rl.py hl-build <session.json> "D:\clips\match.mkv" --out reel.mp4
```

- Each goal becomes a window (default 8s before → 5s after). Overlapping windows
  are merged so footage isn't repeated.
- The sync offset is the one thing that has to be right. If clips land slightly
  early/late, correct the drift without re-recording:
  `--offset -0.5` (shift everything half a second earlier).
- Preview the cut plan without ffmpeg or a video: `--dry-run`.

```bat
:: see exactly what would be cut:
python rl.py hl-build <session.json> --dry-run
```

---

## Project layout

```
rl-stats-suite/
├── rl.py                 # unified launcher (all subcommands)
├── rlstats/              # SHARED CORE
│   ├── events.py         #   event names + payload schemas
│   ├── listener.py       #   reconnecting WebSocket client + pub/sub
│   ├── mock_server.py    #   simulated Stats API (no game needed)
│   └── config.py         #   config loading
├── tracker/              # TOOL 1: db, recorder, Flask dashboard (+ templates/static)
├── alerts/               # TOOL 2: rule engine, push server, OBS overlay/
├── highlights/           # TOOL 3: sync, recorder, ffmpeg editor
└── tests/                # unit + end-to-end tests
```

Build order, dependency-first: shared core → tracker → alerts → highlights.

---

## Testing

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Covers the listener/mock end-to-end, the tracker's analytics SQL, the alert rule
engine + the threaded→async push bridge (with a real overlay client), and the
highlight sync math + clip planning. The tests spin up the mock server on
loopback, so no game and no ffmpeg are required.

---

## Notes & limitations

- The Stats API is real-time and local-only. It can't reach back into footage
  recorded without it running, and there's no historical/replay data — the SQLite
  database is what builds meaning over many matches.
- Tool 3 assumes you record live alongside the match (OBS or screen capture).
- The mock server's numbers are simulated for testing; they aren't a model of
  real RL balance.
```

---

## License

MIT — see [LICENSE](LICENSE).
