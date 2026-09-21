# Rocket League Stats Suite

Rocket League has a WebSocket built into the game client that streams live
match data to your own machine. Almost nobody uses it. I wanted three things
from it and ended up building all three on one shared core:

1. A personal stats tracker that records every match to SQLite and shows the
   trends on a Flask dashboard.
2. A stream alert app that fires audio and visual alerts to an OBS browser
   source when something happens in the match.
3. A goal highlight editor that lines up goal times with your recording and
   cuts the reel with ffmpeg, so you never scrub through a 40 minute video
   looking for the good bits.

The whole suite also runs against a mock Stats API server, so you can develop,
test and demo everything without launching the game. The 81 tests do exactly
that.

## The Stats API

Enable it once:

1. Open `<Rocket League Install>\TAGame\Config\DefaultStatsAPI.ini`.
2. Set `PacketSendRate` to something above `0`. `10` is fine.
3. Launch the game. The socket listens on `ws://localhost:49123`.

It is real-time only. It knows nothing about recordings or past matches, it
just streams JSON of the form `{ "Event": "...", "Data": { ... } }` while you
play. Every event and its payload is documented in
[`rlstats/events.py`](rlstats/events.py), and the mock server emits exactly
those shapes.

## Setup

Python 3.10 or newer. Developed on 3.13.

```bat
cd rl-stats-suite
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

ffmpeg is only needed for the highlight editor. Install it and make sure it's
on your PATH:

```bat
winget install Gyan.FFmpeg
```

Optionally `copy config.example.json config.json` and edit it for your player
name and ports. Anything you leave out falls back to the defaults in
[`rlstats/config.py`](rlstats/config.py).

## Quick start with no game

Everything goes through one launcher, `rl.py`.

```bat
:: Simulate a match, record it, open the dashboard. One command.
python rl.py demo

:: Or fill the dashboard with fake history instantly:
python rl.py seed --matches 40
python rl.py dashboard
```

To use it with the real game, start the tool you want while Rocket League is
running with the Stats API on. No mock needed.

## Tool 1, the stats tracker

```bat
python rl.py track        :: background recorder, writes each finished match to SQLite
python rl.py dashboard    :: open http://127.0.0.1:5000
```

The recorder ([`tracker/recorder.py`](tracker/recorder.py)) waits for
`MatchEnded`, builds a snapshot per player, adds up the boost usage it
accumulated from the live ticks, and writes one match row plus one row per
player to SQLite ([`tracker/db.py`](tracker/db.py)). The dashboard
([`tracker/dashboard.py`](tracker/dashboard.py)) charts win rate over time,
saves per game, results by arena, session summaries and a recent matches table.

To try it against the mock, open three terminals:

```bat
python rl.py mock           :: terminal 1, loops matches forever
python rl.py track          :: terminal 2
python rl.py dashboard      :: terminal 3
```

### Giving the tracker to someone who doesn't code

`build_exe.bat` produces a single `dist\RLStatsTracker.exe` with PyInstaller.
Send them that file. When they double-click it, it finds their Rocket League
install and switches the Stats API on, records every real match in the
background, and opens the dashboard in their browser. They close the window
to stop. The database lives next to the exe, so their stats survive.

If their game is under `Program Files` and the API isn't on yet, enabling it
needs admin once. The app says so, they right-click and run as administrator
one time, and after that it runs normally. `python rl.py setup-api` does the
same thing by hand.

The `.bat` files in the root (`Start Tracker.bat`, `Open Dashboard.bat`,
`Watch Live Events.bat`) are the same idea for a machine that already has the
project set up.

## Freeplay doesn't count

The Stats API streams every game state, including freeplay and training. The
suite only records a goal or a match when opponents exist on a second team and
the playlist isn't freeplay or training (the list is in `ignore_playlists` in
the config). Otherwise your practice shots end up in the highlight reel and
your win rate is nonsense.

To see what your game sends and how each event gets classified:

```bat
python rl.py monitor --show-state
```

Goals print `[WOULD TRACK]` in a real match and
`[ignored: not a real match]` in freeplay. Useful for checking the filter
against your own install.

## Tool 2, stream alerts

```bat
python rl.py alerts
```

It prints two URLs. In OBS, add a Browser source pointing at the overlay page
(for example `http://127.0.0.1:8080/?hud=0`) on top of your game capture. The
overlay connects to the push socket on its own and animates alerts as events
come in.

Rules live in `alerts/rules.json` (copy
[`alerts/rules.example.json`](alerts/rules.example.json) to start). Each rule
maps an event plus some conditions to an alert with a title, subtitle, icon,
colour, animation and sound. The full schema and the list of built-in
synthesised sounds are at the top of [`alerts/rules.py`](alerts/rules.py).

```json
{
  "name": "Screamer",
  "event": "GoalScored",
  "when": { "scored_by_me": true, "goal_speed": { ">=": 100 } },
  "alert": { "title": "WHAT A SCREAMER!", "subtitle": "{goal_speed} kph rocket",
             "icon": "🚀", "color": "#ff8b32", "animation": "flash", "sound": "airhorn" }
}
```

`http://127.0.0.1:8080/?demo=1` cycles through sample alerts so you can style
the overlay without the game running.

## Tool 3, the highlight editor

The Stats API knows when goals happen. It knows nothing about your video. So
the two clocks get synced through one reference point:

```
recording_start = system clock when the recording started   (the video's t=0)
goal position   = goal_event_time - recording_start
```

Three ways to use it, from least effort to most control.

### Cut from a recording you already made

Record however you already do. OBS, ShadowPlay, Game Bar, whatever gives you
the best quality. The suite only logs goal times and cuts.

```bat
python rl.py hl-log              :: run this while you play, it logs goal times
:: ...record your match as usual, then:
python rl.py hl-cut "C:\Videos\match.mp4"      :: matches goals to the video and cuts the reel
python rl.py hl-cut match.mp4 --dry-run        :: show the plan without cutting
python rl.py hl-cut match.mp4 --offset -1.5    :: nudge if the timing is off
```

It reads the recording's start time from the file's `creation_time` metadata
and lines up the goals you logged by timestamp. Works with any recorder.
Output is `<video>_reel.mp4`.

### Let the suite record the screen itself

```bat
python rl.py hl-auto                 :: or double-click "Auto Highlights.bat"
python rl.py hl-auto --pre 6 --post 4
python rl.py hl-auto --desktop       :: capture the whole desktop instead of the game window
```

Because the suite starts the recording, the video's t=0 and the goal clock are
the same instant, and the reel gets cut the moment the match ends. This needs
Rocket League in borderless or windowed mode. Exclusive fullscreen captures a
black or frozen frame. Output is `data/recordings/match_<ts>.mkv` and
`..._reel.mp4` next to it. If the clips land a bit early or late, set
`highlight_capture_sync_offset` in the config (more negative means earlier).

### Sync to an OBS recording by hand

Start this at the same moment you hit record in OBS:

```bat
python rl.py hl-record --start --video "D:\clips\match.mkv"
```

Leave it running. Every goal gets logged and the session file is saved live.
Stop with Ctrl+C, then build the reel:

```bat
python rl.py hl-build <session.json> "D:\clips\match.mkv" --out reel.mp4
python rl.py hl-build <session.json> --dry-run      :: see the cut plan, no ffmpeg needed
```

Each goal becomes a window, 8 seconds before to 5 seconds after by default,
and overlapping windows merge so no footage repeats. If everything is
consistently early or late, `--offset -0.5` shifts the whole reel half a second
earlier without re-recording. The sync offset is the only thing that has to be
right.

## Layout

```
rl-stats-suite/
├── rl.py                 # unified launcher, all subcommands
├── rlstats/              # shared core
│   ├── events.py         #   event names and payload schemas
│   ├── listener.py       #   reconnecting WebSocket client with pub/sub
│   ├── mock_server.py    #   simulated Stats API, no game needed
│   └── config.py         #   config loading
├── tracker/              # tool 1: db, recorder, Flask dashboard
├── alerts/               # tool 2: rule engine, push server, OBS overlay
├── highlights/           # tool 3: sync, recorder, ffmpeg editor
└── tests/                # unit and end-to-end tests
```

## Tests

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

81 tests. They cover the listener and mock end to end, the tracker's analytics
SQL, the alert rule engine and the threaded-to-async push bridge with a real
overlay client connected, and the highlight sync maths and clip planning. The
tests start the mock server on loopback, so they need neither the game nor
ffmpeg.

## Limits

The Stats API is live and local. It can't reach back into footage recorded
while it wasn't running, and there is no replay or history endpoint. The SQLite
database is what turns single matches into something worth looking at over
time. The mock server's numbers are made up for testing and say nothing about
real Rocket League balance.

## License

MIT, see [LICENSE](LICENSE).
