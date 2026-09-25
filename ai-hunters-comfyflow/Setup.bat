@echo off
setlocal EnableExtensions EnableDelayedExpansion
title AI Hunters ComfyFlow v1.0.4 - Setup
cd /d "%~dp0"
set "ROOT=%~dp0"
set "TOOLS=%ROOT%tools"
if not exist "logs" mkdir "logs"
if not exist "!TOOLS!" mkdir "!TOOLS!"

rem Portable / per-user tool versions downloaded when missing (no admin rights needed)
set "PY_VER=3.12.8"
set "PY_URL=https://www.python.org/ftp/python/%PY_VER%/python-%PY_VER%-amd64.exe"
set "GIT_URL=https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/MinGit-2.47.1-64-bit.zip"
set "NODE_VER=v22.12.0"
set "NODE_URL=https://nodejs.org/dist/%NODE_VER%/node-%NODE_VER%-win-x64.zip"
set "VCREDIST_URL=https://aka.ms/vs/17/release/vc_redist.x64.exe"

echo.
echo  ============================================================
echo    AI Hunters ComfyFlow v1.0.4  -  Setup for Windows 11
echo    Missing tools are downloaded automatically into .\tools
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
echo [1/6] Tools: Python, Git, Node.js
where curl >nul 2>&1
if errorlevel 1 (
  echo [ERROR] curl.exe is missing - it ships with Windows 10/11. Update Windows and run Setup.bat again.
  goto :fail
)
call :ensure_python
if errorlevel 1 goto :fail
call :ensure_git
if errorlevel 1 goto :fail
call :ensure_node
if errorlevel 1 goto :fail

rem ---------------------------------------------------------------- 3. backend venv
echo.
echo [2/6] Backend: Python virtual environment + dependencies
if not exist "backend\.venv\Scripts\python.exe" (
  echo       Creating backend\.venv
  "!PY!" -m venv "backend\.venv"
  if errorlevel 1 goto :fail
)
"backend\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
"backend\.venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt"
if errorlevel 1 goto :fail
echo [OK] Backend dependencies installed

rem ---------------------------------------------------------------- 4. frontend
echo.
echo [3/6] Frontend: npm packages
pushd frontend
call npm install --no-audit --no-fund
set "NPM_RC=!errorlevel!"
popd
if not "!NPM_RC!"=="0" goto :fail
echo [OK] Frontend dependencies installed

rem ---------------------------------------------------------------- 5. VC++ runtime (needed by PyTorch)
echo.
echo [4/6] Microsoft Visual C++ runtime
if /i "%INSTALL_COMFYUI%"=="false" goto :vc_done
call :ensure_vcredist
:vc_done

rem ---------------------------------------------------------------- 6. ComfyUI
echo.
echo [5/6] ComfyUI + PyTorch + custom nodes
if /i "%INSTALL_COMFYUI%"=="false" (
  echo [SKIP] INSTALL_COMFYUI=false in .env - using your own ComfyUI at %COMFYUI_HOST%:%COMFYUI_PORT%
  goto :comfy_done
)
"backend\.venv\Scripts\python.exe" "scripts\setup_comfyui.py"
if errorlevel 1 goto :fail
:comfy_done

rem ---------------------------------------------------------------- 7. data folders
echo.
echo [6/6] Preparing data folders
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
echo          Setup can be re-run safely - finished steps are skipped.
echo.
pause
exit /b 1

rem ================================================================ helpers
:load_env
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do set "%%A=%%B"
exit /b 0

:download
rem %1 = url, %2 = target file
echo       Downloading %~nx2 ...
curl -L --fail --retry 3 --retry-delay 3 --progress-bar -o "%~2" "%~1"
if errorlevel 1 (
  echo [ERROR] Download failed: %~1
  echo         Check the internet connection / proxy and run Setup.bat again.
  if exist "%~2" del /q "%~2"
  exit /b 1
)
exit /b 0

rem ---------------------------------------------------------------- Python
:ensure_python
set "PY="
if exist "!TOOLS!\python\python.exe" (
  set "PY=!TOOLS!\python\python.exe"
  goto :python_found
)
for %%V in (3.12 3.11 3.10 3.13) do (
  if not defined PY (
    for /f "delims=" %%P in ('py -%%V -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%P"
  )
)
if defined PY goto :python_found
for /f "delims=" %%P in ('python -c "import sys; print(sys.executable) if (3,10) <= sys.version_info[:2] <= (3,13) else None" 2^>nul') do set "PY=%%P"
if defined PY goto :python_found

echo [..] Python 3.10-3.13 not found - installing Python %PY_VER% into tools\python
call :download "%PY_URL%" "!TOOLS!\python-installer.exe"
if errorlevel 1 exit /b 1
echo       Installing silently for the current user (no admin rights needed) ...
start "" /wait "!TOOLS!\python-installer.exe" /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0 Shortcuts=0 AssociateFiles=0 TargetDir="!TOOLS!\python"
del /q "!TOOLS!\python-installer.exe" >nul 2>&1
if not exist "!TOOLS!\python\python.exe" (
  echo [ERROR] Python could not be installed into !TOOLS!\python
  exit /b 1
)
set "PY=!TOOLS!\python\python.exe"
:python_found
for /f "delims=" %%v in ('call "!PY!" --version 2^>^&1') do echo [OK] %%v  -  !PY!
exit /b 0

rem ---------------------------------------------------------------- Git
:ensure_git
if exist "!TOOLS!\git\cmd\git.exe" goto :git_local
where git >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%v in ('git --version') do echo [OK] %%v
  exit /b 0
)
echo [..] Git not found - downloading portable Git (MinGit) into tools\git
call :download "%GIT_URL%" "!TOOLS!\mingit.zip"
if errorlevel 1 exit /b 1
if not exist "!TOOLS!\git" mkdir "!TOOLS!\git"
tar -xf "!TOOLS!\mingit.zip" -C "!TOOLS!\git"
if errorlevel 1 (
  echo [ERROR] Could not unpack Git.
  exit /b 1
)
del /q "!TOOLS!\mingit.zip"
:git_local
set "PATH=!TOOLS!\git\cmd;%PATH%"
for /f "delims=" %%v in ('git --version') do echo [OK] %%v  -  portable in tools\git
exit /b 0

rem ---------------------------------------------------------------- Node.js
:ensure_node
if exist "!TOOLS!\node\node.exe" goto :node_local
where npm >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%v in ('node --version') do echo [OK] Node.js %%v
  exit /b 0
)
echo [..] Node.js not found - downloading portable Node.js %NODE_VER% into tools\node
call :download "%NODE_URL%" "!TOOLS!\node.zip"
if errorlevel 1 exit /b 1
tar -xf "!TOOLS!\node.zip" -C "!TOOLS!"
if errorlevel 1 (
  echo [ERROR] Could not unpack Node.js.
  exit /b 1
)
if exist "!TOOLS!\node" rmdir /s /q "!TOOLS!\node"
ren "!TOOLS!\node-%NODE_VER%-win-x64" node
del /q "!TOOLS!\node.zip"
:node_local
set "PATH=!TOOLS!\node;%PATH%"
for /f "delims=" %%v in ('node --version') do echo [OK] Node.js %%v  -  portable in tools\node
exit /b 0

rem ---------------------------------------------------------------- VC++ runtime
:ensure_vcredist
if exist "%SystemRoot%\System32\vcruntime140_1.dll" if exist "%SystemRoot%\System32\msvcp140.dll" (
  echo [OK] Visual C++ runtime present
  exit /b 0
)
echo [..] Visual C++ runtime missing - downloading it (Windows will ask for permission)
call :download "%VCREDIST_URL%" "!TOOLS!\vc_redist.x64.exe"
if errorlevel 1 exit /b 0
"!TOOLS!\vc_redist.x64.exe" /install /quiet /norestart
set "VC_RC=!errorlevel!"
if "!VC_RC!"=="3010" set "VC_RC=0"
if "!VC_RC!"=="1638" set "VC_RC=0"
if not "!VC_RC!"=="0" (
  echo [WARN] Visual C++ runtime was not installed. If ComfyUI fails with a DLL error, run tools\vc_redist.x64.exe yourself.
  exit /b 0
)
del /q "!TOOLS!\vc_redist.x64.exe" >nul 2>&1
echo [OK] Visual C++ runtime installed
exit /b 0
