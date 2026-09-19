@echo off
setlocal
set "TAICHI_FLOW_ROOT=%~dp0"
set "TAICHI_FLOW_ROOT=%TAICHI_FLOW_ROOT:~0,-1%"
if exist "%TAICHI_FLOW_ROOT%\portable-manifest.json" (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%TAICHI_FLOW_ROOT%\scripts\portable\Stop-Taichi-Flow-Portable.ps1" -Root "%TAICHI_FLOW_ROOT%"
) else (
  powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%TAICHI_FLOW_ROOT%\scripts\desktop-dev\Stop-DesktopDev.ps1"
)
exit /b %ERRORLEVEL%
