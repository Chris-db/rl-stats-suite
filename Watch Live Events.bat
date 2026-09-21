@echo off
REM Double-click to watch what Rocket League's Stats API is sending, live.
REM This uses the REAL (raw TCP) connection. Open the game and play - events
REM (goals, demos, saves, match start/end) print here and are saved to a file.
cd /d "%~dp0"
title RL Stats - Live Event Capture
".venv\Scripts\python.exe" rl.py capture
pause
