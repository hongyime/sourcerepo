@echo off
chcp 65001 >nul
setlocal

:: Clear host Python environment variables to prevent interference
set PYTHONPATH=
set PYTHONHOME=
set PYTHONUTF8=1

:: Prioritize portable Git and Python for this process only
set "PATH=%~dp0Git\cmd;%~dp0Python;%PATH%"

echo Initiating Zero-Install Repository Synchronization...
echo Repeatable/idempotent: safe to run multiple times.
echo This pulls updates by fetch + fast-forward. Current repos stay unchanged.
echo.
set "SYNC_ARGS=--command-timeout 30"
if "%DRY_RUN%"=="1" set "SYNC_ARGS=%SYNC_ARGS% --dry-run"
if not "%SYNC_ONLY%"=="" set "SYNC_ARGS=%SYNC_ARGS% --only %SYNC_ONLY%"
if "%DRY_RUN%"=="1" goto RUN_SYNC

echo Choose sync mode:
echo   1. Safe sync     - update only clean repos that can fast-forward
echo   2. Interactive   - do the safe sync first, then review dirty/diverged repos
echo                    - can stash, merge, keep local, or keep GitHub per repo
echo.
echo Press Enter for option 1.
set /p MODE="Mode number? "
if "%MODE%"=="2" set "SYNC_ARGS=%SYNC_ARGS% --interactive"

:RUN_SYNC
python "%~dp0sourcerepo\tools\workspace\sync_workspace.py" --workspace "%~dp0." %SYNC_ARGS%

echo.
if not "%NO_PAUSE%"=="1" pause
endlocal
