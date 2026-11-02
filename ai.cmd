@echo off
rem Cross-platform launcher for the .ai workspace CLI (Windows).
rem Auto-detects a Python 3 interpreter; no installation step required when
rem Python 3 is already present. The file protocol remains usable without it.
rem
rem Note: cmd.exe still interprets % and ^ in arguments; quote paths that
rem contain them, or call `python ai.py ...` directly.
setlocal
set "DIR=%~dp0"
set "PY="

where py >nul 2>nul
if errorlevel 1 goto try_python
py -3 -c "import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)" >nul 2>nul
if errorlevel 1 goto try_python
set "PY=py -3"
goto run

:try_python
where python >nul 2>nul
if errorlevel 1 goto no_python
python -c "import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)" >nul 2>nul
if errorlevel 1 goto no_python
set "PY=python"

:run
%PY% "%DIR%ai.py" %*
exit /b %errorlevel%

:no_python
echo error: Python 3 was not found. 1>&2
echo The workspace still works manually: read AGENTS.md and docs\task-flow.md. 1>&2
echo To enable automation, install Python 3 or run the protocol with your agent. 1>&2
exit /b 127
