@echo off
rem Cross-platform launcher for the .ai workspace CLI (Windows).
rem Auto-detects a Python 3 interpreter; no installation step required when
rem Python 3 is already present. The file protocol remains usable without it.
setlocal
set "DIR=%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%DIR%ai.py" %*
    exit /b %errorlevel%
)

where python >nul 2>nul
if %errorlevel%==0 (
    python "%DIR%ai.py" %*
    exit /b %errorlevel%
)

echo error: Python 3 was not found. 1>&2
echo The workspace still works manually: read AGENTS.md and docs\task-flow.md. 1>&2
echo To enable automation, install Python 3 or run the protocol with your agent. 1>&2
exit /b 127
