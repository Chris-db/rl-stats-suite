@echo off
REM ============================================================
REM  STEP 1: Double-click this BEFORE/while you play.
REM  It just records WHEN goals happen. Leave the window open.
REM  Record your match in OBS / ShadowPlay however you normally do.
REM  When you're done playing, close this window, then use
REM  "2. Make Highlights (drag video here).bat".
REM ============================================================
cd /d "%~dp0"
title RL Stats - Goal Logger (leave open while playing)
echo.
echo  Logging goals while you play...
echo  - Leave this window OPEN.
echo  - Record your match in OBS / ShadowPlay as usual.
echo  - When finished, drag your video onto:
echo       "2. Make Highlights (drag video here).bat"
echo.
".venv\Scripts\python.exe" rl.py hl-log
echo.
echo  (Goal logging stopped. You can close this window.)
pause
