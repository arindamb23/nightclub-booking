@echo off
setlocal EnableExtensions EnableDelayedExpansion
title AI Hunters ComfyFlow v1.0.0 - Setup
cd /d "%~dp0"
set "ROOT=%~dp0"
if not exist "logs" mkdir "logs"

echo.
echo  ============================================================
echo    AI Hunters ComfyFlow v1.0.0  -  Setup for Windows 11
echo  ============================================================
echo.

rem ---------------------------------------------------------------- 1. .env
if exist ".env" goto :env_ok
copy /y ".env.example" ".env" >nul
echo [OK] Created .env from .env.example
goto :env_loaded
:env_ok
echo [OK] Using the existing .env
:env_loaded
call :load_env

rem ---------------------------------------------------------------- 2. tools
echo.
echo [1/5] Checking required tools
call :find_python
if errorlevel 1 goto :fail
where git >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Git was not found. Install it, then run Setup.bat again:
  echo         winget install -e --id Git.Git
  goto :fail
)
echo [OK] Git found
where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js was not found. Install the LTS version, then run Setup.bat again:
  echo         winget install -e --id OpenJS.NodeJS.LTS
  goto :fail
)
for /f "delims=" %%v in ('node --version') do echo [OK] Node.js %%v found

rem ---------------------------------------------------------------- 3. backend venv
echo.
echo [2/5] Backend: Python virtual environment + dependencies
if not exist "backend\.venv\Scripts\python.exe" (
  echo       Creating backend\.venv
  !PY! -m venv "backend\.venv"
  if errorlevel 1 goto :fail
)
"backend\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
"backend\.venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt"
if errorlevel 1 goto :fail
echo [OK] Backend dependencies installed

rem ---------------------------------------------------------------- 4. frontend
echo.
echo [3/5] Frontend: npm packages
pushd frontend
call npm install --no-audit --no-fund
set "NPM_RC=!errorlevel!"
popd
if not "!NPM_RC!"=="0" goto :fail
echo [OK] Frontend dependencies installed

rem ---------------------------------------------------------------- 5. ComfyUI
echo.
echo [4/5] ComfyUI + PyTorch + custom nodes
if /i "%INSTALL_COMFYUI%"=="false" (
  echo [SKIP] INSTALL_COMFYUI=false in .env - using your own ComfyUI at %COMFYUI_HOST%:%COMFYUI_PORT%
  goto :comfy_done
)
"backend\.venv\Scripts\python.exe" "scripts\setup_comfyui.py"
if errorlevel 1 goto :fail
:comfy_done

rem ---------------------------------------------------------------- 6. data folders
echo.
echo [5/5] Preparing data folders
for %%D in (data data\workflows data\runs data\outputs data\uploads) do if not exist "%%D" mkdir "%%D"
echo [OK] Data folder ready

echo.
echo  ============================================================
echo    Setup complete.
echo    Start everything with  Start-all.bat
echo    App:      http://localhost:%FRONTEND_PORT%
echo    API:      http://127.0.0.1:%BACKEND_PORT%/docs
echo    ComfyUI:  http://%COMFYUI_HOST%:%COMFYUI_PORT%
echo  ============================================================
echo.
pause
exit /b 0

:fail
echo.
echo [FAILED] Setup did not finish. Read the messages above, fix the problem and run Setup.bat again.
echo.
pause
exit /b 1

rem ================================================================ helpers
:load_env
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do set "%%A=%%B"
exit /b 0

:find_python
set "PY="
for %%V in (3.12 3.11 3.10 3.13) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [ERROR] Python 3.10 - 3.13 was not found. Install Python 3.12, then run Setup.bat again:
  echo         winget install -e --id Python.Python.3.12
  exit /b 1
)
for /f "delims=" %%v in ('!PY! --version 2^>^&1') do echo [OK] %%v found
exit /b 0
