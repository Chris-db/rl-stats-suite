@echo off
REM ============================================================
REM  STEP 2: DRAG your recorded video FILE onto this .bat icon.
REM  It finds the goals you logged and cuts a highlight reel
REM  saved next to your video as "<name>_reel.mp4".
REM ============================================================
cd /d "%~dp0"
title RL Stats - Make Highlights

if "%~1"=="" (
  echo.
  echo  HOW TO USE:
  echo    Drag your recorded video FILE and drop it ONTO this .bat icon.
  echo    ^(an OBS / ShadowPlay .mp4 or .mkv^)
  echo.
  echo  A highlight reel will be saved next to your video.
  echo.
  pause
  exit /b
)

echo.
echo  Making highlights from:
echo    %~1
echo.
".venv\Scripts\python.exe" rl.py hl-cut "%~1"
echo.
pause
