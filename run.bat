@echo off
setlocal
cd /d "%~dp0"
title OrthoParity data pipeline

rem ---- find Python 3.10 or newer ------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
    echo Python is not installed. Install Python 3.12 from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup. Then double-click run.bat again.
    pause
    exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" || (
    echo This needs Python 3.10 or newer. Install Python 3.12 from https://www.python.org/downloads/
    pause
    exit /b 1
)

rem ---- one private Python environment in .venv (first run only) ------------
if not exist ".venv\Scripts\python.exe" (
    echo Creating a private Python environment in .venv - one time only, about a minute...
    %PY% -m venv .venv || goto :fail
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail

rem ---- run the step named on the command line, or ask for one --------------
if not "%~1"=="" (
    ".venv\Scripts\python.exe" orthoparity.py %*
    goto :done
)
".venv\Scripts\python.exe" orthoparity.py list
echo.
set "STEP="
set /p "STEP=Type a step or group name and press Enter (for example: predicates): "
if "%STEP%"=="" goto :done
".venv\Scripts\python.exe" orthoparity.py %STEP%

:done
echo.
pause
exit /b 0

:fail
echo Setup failed. See the message above.
pause
exit /b 1
