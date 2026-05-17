@echo off
echo Starting Knowledge Base Auto Test (background)...
echo Runs every 30 min until June 7th.
echo Log: %~dp0auto_test.log
echo.
start "KB Auto Test" /MIN powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0auto_test.ps1"
echo Auto test started in background.
echo Close this window - it runs independently.
timeout /t 3
