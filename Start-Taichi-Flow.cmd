@echo off
setlocal
set "TAICHI_FLOW_ROOT=%~dp0"
set "TAICHI_FLOW_ROOT=%TAICHI_FLOW_ROOT:~0,-1%"
if exist "%TAICHI_FLOW_ROOT%\portable-manifest.json" (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%TAICHI_FLOW_ROOT%\scripts\portable\Start-Taichi-Flow-Portable.ps1" -Root "%TAICHI_FLOW_ROOT%"
) else (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%TAICHI_FLOW_ROOT%\scripts\desktop-dev\Start-DesktopDev.ps1" -Mode dev
)
set "TAICHI_FLOW_EXIT=%ERRORLEVEL%"
if not "%TAICHI_FLOW_EXIT%"=="0" (
  echo.
  echo Taichi-Flow startup failed with exit code %TAICHI_FLOW_EXIT%.
  pause
)
exit /b %TAICHI_FLOW_EXIT%
