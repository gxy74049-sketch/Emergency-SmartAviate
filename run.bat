@echo off
REM ============================================================
REM  run.bat - Emergency-SmartAviate launcher (Windows)
REM  ASCII only: safe under any Windows code page (GBK/UTF-8/...).
REM  - cd to this script folder, so it runs from any path
REM  - reuse .venv only if it really works (a .venv copied from
REM    another PC points to a Python that no longer exists)
REM  - rebuild .venv with a local Python 3.10+ when needed
REM  - fall back to the system Python, with install hints if none
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"
title Emergency-SmartAviate Launcher

set "VENV_DIR=.venv"
set "VENV_PY=.venv\Scripts\python.exe"
set "REQ=requirements.txt"
set "PYCMD="
set "SYS_PY="

REM ---------- 1) Pick a usable system Python (path independent) ----------
call :probe "py -3"
if not defined SYS_PY call :probe "python"

REM ---------- 2) Reuse the project venv only if it really works ----------
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYCMD=%VENV_PY%"
        goto :launch
    )
    echo [INFO] Existing .venv is broken: it was created on another PC and
    echo [INFO] its base interpreter no longer exists. Rebuilding it now.
)

REM ---------- 3) Create or rebuild the venv with the local Python ----------
if defined SYS_PY call :ensure_venv
if defined PYCMD goto :launch

REM ---------- 4) Fall back to the system Python ----------
if defined SYS_PY (
    set "PYCMD=%SYS_PY%"
    goto :launch
)

echo [ERROR] No usable Python 3.10+ was found.
echo         Install Python and enable "Add python.exe to PATH":
echo         https://www.python.org/downloads/
echo.
pause
exit /b 127

REM ==================== subroutines ====================
:ensure_venv
if exist "%VENV_PY%" (
    echo [INFO] Rebuilding .venv with %SYS_PY% ...
    if exist ".venv.old" rmdir /s /q ".venv.old" >nul 2>&1
    move ".venv" ".venv.old" >nul 2>&1
) else (
    echo [INFO] Creating .venv with %SYS_PY% ...
)
REM --system-site-packages makes the venv inherit installed packages (offline OK)
%SYS_PY% -m venv --system-site-packages "%VENV_DIR%" >nul 2>&1
if not exist "%VENV_PY%" (
    echo [WARN] Could not create the venv. Using the system Python instead.
    exit /b 0
)
"%VENV_PY%" -c "import streamlit" >nul 2>&1
if errorlevel 1 if exist "%REQ%" (
    echo [INFO] Installing dependencies, this may take a few minutes ...
    "%VENV_PY%" -m pip install --disable-pip-version-check -r "%REQ%"
)
"%VENV_PY%" -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo [WARN] The venv is missing dependencies. Using the system Python instead.
    exit /b 0
)
set "PYCMD=%VENV_PY%"
exit /b 0

:launch
echo [RUN] %PYCMD% launcher.py
echo.
%PYCMD% launcher.py
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%

:probe
REM Verify the candidate runs and is Python 3.10+; on success store it.
if defined SYS_PY exit /b 0
%~1 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "SYS_PY=%~1"
exit /b 0
