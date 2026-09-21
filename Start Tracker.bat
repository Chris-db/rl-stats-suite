@echo off
REM Double-click to start recording your matches in the background.
REM Leave this window open while you play. Close it (or press Ctrl+C) to stop.
cd /d "%~dp0"
title RL Stats - Background Tracker
echo Recording matches to your stats database...
echo (Leave this window open while you play. Close it to stop.)
echo.
".venv\Scripts\python.exe" rl.py track
pause
