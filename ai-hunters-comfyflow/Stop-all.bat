@echo off
setlocal EnableExtensions EnableDelayedExpansion
title AI Hunters ComfyFlow v1.0.7 - Stop
cd /d "%~dp0"

if not exist ".env" (
  echo [ERROR] .env not found - nothing to stop.
  exit /b 1
)
call :load_env

echo.
echo  Stopping AI Hunters ComfyFlow ...
call :kill_port %FRONTEND_PORT% Frontend
call :kill_port %BACKEND_PORT% Backend
if /i "%~1"=="keep-comfyui" (
  echo [SKIP] ComfyUI left running
) else (
  call :kill_port %COMFYUI_PORT% ComfyUI
)
rem Close the console windows opened by Start-all.bat
taskkill /FI "WINDOWTITLE eq ComfyFlow-*" /T /F >nul 2>&1
echo [OK] Done.
echo.
timeout /t 3 >nul
exit /b 0

rem ================================================================ helpers
:load_env
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do set "%%A=%%B"
exit /b 0

:kill_port
set "FOUND="
for /f "tokens=5" %%I in ('netstat -ano ^| findstr /R /C:":%~1 .*LISTENING"') do (
  if not "%%I"=="0" (
    taskkill /PID %%I /T /F >nul 2>&1
    set "FOUND=1"
  )
)
if defined FOUND (echo [OK] %~2 stopped - port %~1) else (echo [--] %~2 was not running - port %~1)
exit /b 0
