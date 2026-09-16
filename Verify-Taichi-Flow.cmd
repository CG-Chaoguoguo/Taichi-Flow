@echo off
setlocal
set "TAICHI_FLOW_ROOT=%~dp0"
set "TAICHI_FLOW_ROOT=%TAICHI_FLOW_ROOT:~0,-1%"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%TAICHI_FLOW_ROOT%\scripts\portable\Verify-Taichi-Flow-Portable.ps1" -Root "%TAICHI_FLOW_ROOT%"
set "TAICHI_FLOW_EXIT=%ERRORLEVEL%"
if not "%TAICHI_FLOW_EXIT%"=="0" (
  echo.
  echo Portable verification failed with exit code %TAICHI_FLOW_EXIT%.
  pause
)
exit /b %TAICHI_FLOW_EXIT%
