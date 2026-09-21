@echo off
REM Rebuild the shareable standalone tracker (dist\RLStatsTracker.exe).
cd /d "%~dp0"
echo Building RLStatsTracker.exe ...
".venv\Scripts\python.exe" -m PyInstaller --onefile --name RLStatsTracker --noconfirm ^
  --add-data "tracker\templates;tracker\templates" ^
  --add-data "tracker\static;tracker\static" ^
  app.py
echo.
echo Done. Share this single file with anyone:  dist\RLStatsTracker.exe
pause
