# Rocket League Stats Suite — Build Spec

A suite of three tools for Rocket League players and creators, all built on one shared core that reads the game's local Stats API. Build the shared core first, then the tools in order.

---

## The Stats API (what we're reading)

Rocket League ships a **client-side WebSocket** that streams live match data from the player's own machine. The player enables it once by editing `<Install Dir>\TAGame\Config\DefaultStatsAPI.ini` and setting `PacketSendRate` above 0. The socket then listens on `ws://localhost:49123` (default port).

It is **real-time only** — it never touches recorded video or past matches. It emits JSON messages of the form `{ "Event": "...", "Data": { ... } }`.

Events we care about:
- `UpdateState` — periodic tick with full player + game state (score, boost, speed, saves, etc.)
- `GoalScored` — fires on each goal, includes scorer, assister, goal speed
- `StatfeedEvent` — demos, saves, and other stat moments
- `MatchEnded` — final result and winning team
- `MatchCreated` / `MatchDestroyed` — match lifecycle

---

## Shared Core: the Event Listener

A single reusable module that connects to the socket and dispatches events. Every tool imports this.

Responsibilities:
- Connect to `ws://localhost:49123`, auto-reconnect if the game isn't running yet.
- Parse each incoming JSON message into an event name + data payload.
- Let tools subscribe to specific events with callbacks (e.g. `on("GoalScored", handler)`).
- Handle the socket dropping when the player exits a match, without crashing.

Suggested language: **Python** (plays to existing Flask/SQLite skills). Use a websocket client library and a simple pub/sub dispatch pattern.

---

## Tool 1 — Personal Stats Tracker

Runs in the background, records every match, and shows trends over time.

- On `MatchEnded`, capture the final stats snapshot per player and write one row to a **SQLite** database (goals, shots, saves, assists, demos, boost usage, win/loss, arena, timestamp).
- A separate **Flask dashboard** reads the database and renders charts: win rate over time, average saves per game, performance by arena, session summaries.
- The live API gives the raw feed; the database is what creates meaning over many matches. The dashboard is the product.

This is the recommended **first build** — it's the most self-contained and leans hardest on existing skills.

---

## Tool 2 — Stream Alert App

Fires custom audio/visual alerts for streamers when chosen events happen.

- Listen for trigger events (`GoalScored`, `StatfeedEvent` for demos/saves, supersonic, etc.).
- Match each event against user-defined rules ("when I score → play sound X + show animation Y").
- Outputs go to an **HTML overlay** that OBS loads as a browser source. The app pushes events to the overlay over its own local socket; the overlay animates them.
- OBS composites: game capture + overlay layer on top. The app is the brain deciding when things fire.

Target users: smaller RL content creators who want polished, automatic alerts.

---

## Tool 3 — Goal Highlight Auto-Editor

Automatically cuts a full match recording down to just the moments around each goal (e.g. 8 seconds before to 5 seconds after), then stitches them into one highlight reel.

**Core mechanic — timeline sync.** The API knows *when* goals happen; it does not know the video. So we sync two clocks:

1. When recording starts, record the system clock time — this is the video's zero point.
2. The listener logs every `GoalScored` event with its own system time.
3. For each goal: `position_in_video = event_time − recording_start_time`.

After the match we have a list of in-video positions. Hand them to **ffmpeg**: cut a window around each, concatenate the clips, output the reel.

**Critical risk to get right:** the sync offset. If the timestamp math drifts, clips land on the wrong moment. The whole tool's reliability rests on nailing that single reference point. Everything else (the ffmpeg cutting and joining) is mechanical.

Note: this assumes recording happens live alongside the match (OBS or screen capture). The API can't reach back into footage that was recorded without it running.

---

## Suggested Tech Stack

| Part | Choice |
|---|---|
| Event listener | Python + websocket client |
| Stats storage | SQLite |
| Stats dashboard | Flask + a charting library |
| Alert overlay | HTML/CSS/JS (OBS browser source) |
| Video cutting | ffmpeg via subprocess |

## Recommended Build Order

1. Shared event listener (everything depends on it).
2. Stats tracker (self-contained, fastest win).
3. Stream alert app (introduces the overlay pattern).
4. Goal highlight editor (hardest — the sync offset is the real work).
