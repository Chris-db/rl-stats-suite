@echo off
REM Double-click, then play. The tool records your screen, clips every goal
REM (a few seconds before & after), and stitches a highlight reel automatically
REM when the match ends. Press Ctrl+C in this window to stop early.
REM Tip: run Rocket League in BORDERLESS/WINDOWED so the capture isn't black.
cd /d "%~dp0"
title RL Stats - Auto Highlights
".venv\Scripts\python.exe" rl.py hl-auto
pause
