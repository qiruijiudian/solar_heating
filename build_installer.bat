@echo off
rem Compile the client installer (installer\setup exe) from dist + project data.
rem Step 1: run build_exe.bat to produce dist\SolarHeatingDesign.
rem Step 2: run this script. All data files are pulled by installer.iss directly.
cd /d "%~dp0"
set "ISCC=D:\tools\inno6\app\ISCC.exe"
if not exist "%ISCC%" (
  echo Missing Inno compiler: %ISCC%
  pause
  exit /b 1
)
if not exist "dist\SolarHeatingDesign\SolarHeatingDesign.exe" (
  echo Missing dist\SolarHeatingDesign.exe - run build_exe.bat first.
  pause
  exit /b 1
)
"%ISCC%" installer.iss
if errorlevel 1 (
  echo INSTALLER BUILD FAILED
  pause
  exit /b 1
)
echo.
echo OK - installer exe is in the installer folder.
pause
