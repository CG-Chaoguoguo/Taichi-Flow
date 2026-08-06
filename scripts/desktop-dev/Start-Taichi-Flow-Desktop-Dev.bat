@echo off
setlocal
set "TAICHI_FLOW_MODE=%~1"
if "%TAICHI_FLOW_MODE%"=="" set "TAICHI_FLOW_MODE=dev"

if /I not "%TAICHI_FLOW_MODE%"=="dev" if /I not "%TAICHI_FLOW_MODE%"=="preview" (
  echo Usage: %~nx0 [dev^|preview]
  pause
  exit /b 2
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-DesktopDev.ps1" -Mode "%TAICHI_FLOW_MODE%"
set "TAICHI_FLOW_EXIT=%ERRORLEVEL%"
if not "%TAICHI_FLOW_EXIT%"=="0" (
  echo.
  echo Taichi-Flow desktop development startup failed with exit code %TAICHI_FLOW_EXIT%.
  echo Review .runtime\desktop-dev\sessions\^<session^>\launcher.log for details.
  pause
)
exit /b %TAICHI_FLOW_EXIT%
