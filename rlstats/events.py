"""Event names and payload schemas for the Rocket League Stats API.

The game ships a client-side WebSocket (ws://localhost:49123) that streams
JSON messages of the form::

    { "Event": "<name>", "Data": { ... } }

This module defines the event-name constants every tool in the suite uses, and
documents the shape of each ``Data`` payload. The mock server
(``rlstats.mock_server``) emits exactly these shapes, so the whole suite can be
developed and tested without the game running.

Payload schemas
---------------

A *player ref* (used inside several payloads) looks like::

    { "id": "p1", "name": "You", "team": 0, "is_local": true }

A *player stat* (full per-player snapshot) looks like::

    {
        "id": "p1", "name": "You", "team": 0, "is_local": true,
        "score": 320, "goals": 1, "shots": 3, "saves": 2,
        "assists": 0, "demos": 1,
        "boost": 47,          # current boost amount, 0-100
        "speed": 1411,        # unreal units / second
        "is_supersonic": false,
        "is_dead": false
    }

UpdateState.Data::

    {
        "game": {
            "arena": "DFH Stadium",
            "playlist": "Ranked Doubles",
            "time_seconds": 145.0,        # time remaining
            "is_overtime": false,
            "teams": [ {"team": 0, "score": 2}, {"team": 1, "score": 1} ]
        },
        "players": [ <player stat>, ... ]
    }

GoalScored.Data::

    {
        "scorer": <player ref>,
        "assister": <player ref> | null,
        "goal_speed": 78.5,               # kph
        "team": 0,
        "scoreboard": [2, 1]
    }

StatfeedEvent.Data::

    {
        "type": "Demolition",             # see STATFEED_* below
        "main_target": <player ref>,
        "secondary_target": <player ref> | null
    }

MatchEnded.Data::

    {
        "arena": "DFH Stadium",
        "playlist": "Ranked Doubles",
        "duration_seconds": 312.4,
        "winner_team": 0,
        "teams": [ {"team": 0, "score": 4}, {"team": 1, "score": 2} ],
        "players": [ <player stat>, ... ]   # may include "boost_used"
    }

MatchCreated.Data::

    { "arena": "DFH Stadium", "playlist": "Ranked Doubles" }

MatchDestroyed.Data::

    {}
"""

from __future__ import annotations

# --- Event names -----------------------------------------------------------

UPDATE_STATE = "UpdateState"
GOAL_SCORED = "GoalScored"
STATFEED_EVENT = "StatfeedEvent"
MATCH_ENDED = "MatchEnded"
MATCH_CREATED = "MatchCreated"
MATCH_DESTROYED = "MatchDestroyed"

#: Wildcard handler key — handlers registered under this receive every event.
ALL = "*"

ALL_EVENTS = (
    UPDATE_STATE,
    GOAL_SCORED,
    STATFEED_EVENT,
    MATCH_ENDED,
    MATCH_CREATED,
    MATCH_DESTROYED,
)

# --- Statfeed event types --------------------------------------------------

STATFEED_DEMOLITION = "Demolition"
STATFEED_SAVE = "Save"
STATFEED_EPIC_SAVE = "Epic Save"
STATFEED_SHOT_ON_GOAL = "Shot on Goal"
STATFEED_CENTER_BALL = "Center Ball"
STATFEED_POOL_SHOT = "Pool Shot"
STATFEED_ASSIST = "Assist"
STATFEED_GOAL = "Goal"
