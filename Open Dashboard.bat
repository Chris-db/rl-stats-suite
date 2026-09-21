@echo off
REM Double-click to open your stats dashboard in the browser.
cd /d "%~dp0"
title RL Stats - Dashboard
start "" ".venv\Scripts\python.exe" rl.py dashboard
timeout /t 2 >nul
start "" http://127.0.0.1:5000
echo Dashboard running at http://127.0.0.1:5000
echo Close the other "Dashboard" window to stop it.
