@echo off
REM Jikyeobom CCTV demo - local server for webcam (Windows)
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  start "" http://localhost:8000
  py -m http.server 8000
  goto :eof
)
where python >nul 2>nul
if %errorlevel%==0 (
  start "" http://localhost:8000
  python -m http.server 8000
  goto :eof
)
echo Python is not installed. Install it from https://www.python.org/downloads/ (check "Add python.exe to PATH") and run this file again.
pause
