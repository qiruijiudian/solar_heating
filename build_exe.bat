@echo off
rem Build the client EXE (onedir) for the solar heating design tool.
rem Uses the shared Windows venv from the solarheatingfirst project.
cd /d "%~dp0"
set "PY=D:\solarheatingfirst\Solar_heating\.venv-win\Scripts\python.exe"
if not exist "%PY%" (
  echo Missing virtualenv python: %PY%
  pause
  exit /b 1
)
"%PY%" -m PyInstaller --noconfirm --clean --onedir --name SolarHeatingDesign ^
  --collect-all bokeh --collect-all panel --collect-all holoviews ^
  --collect-all hvplot --collect-all param ^
  thermal_storage_gui.py
if errorlevel 1 (
  echo BUILD FAILED
  pause
  exit /b 1
)
echo.
echo BUILD OK -^> dist\SolarHeatingDesign\SolarHeatingDesign.exe
pause
