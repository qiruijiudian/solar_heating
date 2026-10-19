@echo off
rem Launcher for the "ceshi clzk" project dashboard.
rem Borrows the Windows venv from the solarheatingfirst project.
cd /d "%~dp0"
set "PY=D:\solarheatingfirst\Solar_heating\.venv-win\Scripts\python.exe"
if not exist "%PY%" (
  echo Missing virtualenv python: %PY%
  echo Create it in the solarheatingfirst project first:
  echo   py -3.13 -m venv .venv-win
  echo   .venv-win\Scripts\python.exe -m pip install numpy pandas openpyxl panel hvplot holoviews bokeh
  pause
  exit /b 1
)
rem Bokeh refuses websockets from 127.0.0.1 by default; allow both hostnames on any port
set "BOKEH_ALLOW_WS_ORIGIN=127.0.0.1,localhost"
"%PY%" thermal_storage_gui.py
pause
