@echo off
rem Run MagnetStudio straight from this folder (Windows) - double-click. No system-wide install:
rem  - with uv (https://docs.astral.sh/uv/): uv makes .venv here and even fetches Python if needed;
rem  - otherwise with Python 3.10+: a local .venv is created on the first run.
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if not errorlevel 1 (
    uv run --extra ai python -m magnetstudio %*
    goto :end
)

set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=python"
if not defined PY (
    echo MagnetStudio needs Python 3.10+ or uv. Easiest - install uv ^(one line in PowerShell^), then run this again:
    echo     powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    echo or install Python from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^)
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo First run: creating a local environment in .venv ...
    %PY% -m venv .venv || goto :fail
)
".venv\Scripts\python.exe" packaging\ensure_env.py || goto :fail
".venv\Scripts\python.exe" -m magnetstudio %*
goto :end

:fail
echo Setup failed - see the messages above.
pause
exit /b 1

:end
endlocal
