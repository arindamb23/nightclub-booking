@echo off
setlocal EnableExtensions EnableDelayedExpansion
title AI Hunters ComfyFlow v1.0.10 - Start
cd /d "%~dp0"
set "ROOT=%~dp0"
rem Portable tools downloaded by Setup.bat take precedence
if exist "%ROOT%tools\node\node.exe" set "PATH=%ROOT%tools\node;%PATH%"
if exist "%ROOT%tools\git\cmd\git.exe" set "PATH=%ROOT%tools\git\cmd;%PATH%"

if not exist ".env" (
  echo [ERROR] .env not found. Run Setup.bat first.
  pause
  exit /b 1
)
call :load_env
if not exist "backend\.venv\Scripts\python.exe" goto :need_setup
if not exist "frontend\node_modules" goto :need_setup

echo.
echo  AI Hunters ComfyFlow v1.0.10
echo  ----------------------------------------------

rem ---------------------------------------------------------------- ComfyUI
call :abs COMFY_DIR "%COMFYUI_DIR%"
call :abs COMFY_PY "%COMFYUI_PYTHON%"
call :port_in_use %COMFYUI_PORT%
if not errorlevel 1 (
  echo [OK] ComfyUI already running on port %COMFYUI_PORT%
  goto :backend
)
if not exist "!COMFY_DIR!\main.py" (
  echo [WARN] ComfyUI is not installed in !COMFY_DIR!
  echo        Run Setup.bat, or set COMFYUI_HOST / COMFYUI_PORT in .env to your own ComfyUI.
  goto :backend
)
"backend\.venv\Scripts\python.exe" "scripts\prestart.py"
echo [..] Starting ComfyUI on port %COMFYUI_PORT% (console also saved to logs\comfyui.log)
start "ComfyFlow-ComfyUI" /min cmd /k ""!COMFY_PY!" "%ROOT%scripts\run_comfyui.py" "!COMFY_DIR!" --listen %COMFYUI_HOST% --port %COMFYUI_PORT% --preview-method auto %COMFYUI_EXTRA_ARGS%"

:backend
rem ---------------------------------------------------------------- backend
call :port_in_use %BACKEND_PORT%
if not errorlevel 1 (
  echo [OK] Backend already running on port %BACKEND_PORT%
) else (
  echo [..] Starting backend on port %BACKEND_PORT%
  start "ComfyFlow-Backend" /min /D "%ROOT%backend" cmd /k ".venv\Scripts\python.exe -m app"
)

rem ---------------------------------------------------------------- frontend
call :port_in_use %FRONTEND_PORT%
if not errorlevel 1 (
  echo [OK] Frontend already running on port %FRONTEND_PORT%
) else (
  echo [..] Starting frontend on port %FRONTEND_PORT%
  start "ComfyFlow-Frontend" /min /D "%ROOT%frontend" cmd /k "npm run dev"
)

rem ---------------------------------------------------------------- wait + open
echo [..] Waiting for the backend
set /a TRIES=0
:wait_backend
set /a TRIES+=1
curl -s -o nul "http://127.0.0.1:%BACKEND_PORT%/api/health"
if not errorlevel 1 goto :ready
if !TRIES! geq 40 (
  echo [WARN] The backend did not answer yet. Check the "ComfyFlow-Backend" window.
  goto :open
)
timeout /t 1 /nobreak >nul
goto :wait_backend
:ready
echo [OK] Backend is up
:open
timeout /t 2 /nobreak >nul
start "" "http://localhost:%FRONTEND_PORT%"
echo.
echo  App:      http://localhost:%FRONTEND_PORT%
echo  API:      http://127.0.0.1:%BACKEND_PORT%/docs
echo  ComfyUI:  http://%COMFYUI_HOST%:%COMFYUI_PORT%   (first start can take a minute)
echo.
echo  Use Stop-all.bat to stop everything.
echo.
timeout /t 8 >nul
exit /b 0

:need_setup
echo [ERROR] Dependencies are not installed yet. Run Setup.bat first.
pause
exit /b 1

rem ================================================================ helpers
:load_env
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do set "%%A=%%B"
exit /b 0

:abs
set "%~1=%~f2"
exit /b 0

:port_in_use
netstat -ano | findstr /R /C:":%~1 .*LISTENING" >nul 2>&1
exit /b %errorlevel%
