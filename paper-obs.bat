@echo off
rem ---------------------------------------------------------------------------
rem Double-click this file to start Paper Obs and open it in the browser.
rem Keep this window open: closing it stops the server.
rem
rem It runs the lab inside WSL, in this folder, and lets the serve command pick
rem a free port and open the page itself.
rem ---------------------------------------------------------------------------

title Paper Obs

if not exist "%~dp0.venv" (
  echo.
  echo   The Python environment is missing: %~dp0.venv
  echo   Create it from a terminal with:
  echo.
  echo     python3 -m venv .venv ^&^& .venv/bin/pip install -e ".[dev,api,agents]"
  echo.
  pause
  exit /b 1
)

where wsl.exe >nul 2>nul
if errorlevel 1 (
  echo.
  echo   WSL was not found. Install it with: wsl --install
  echo.
  pause
  exit /b 1
)

cd /d "%~dp0"
wsl.exe --cd "%~dp0" --exec .venv/bin/paper-obs serve
set EXITCODE=%ERRORLEVEL%

echo.
if not "%EXITCODE%"=="0" echo   The server stopped with code %EXITCODE%.
echo   Press any key to close this window.
pause >nul
exit /b %EXITCODE%
