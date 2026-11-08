@echo off
rem Run the Rust `ai` CLI from this checkout (release, then debug, then cargo).
setlocal
set "HERE=%~dp0"

if exist "%HERE%target\release\ai.exe" goto run_release
if exist "%HERE%target\debug\ai.exe" goto run_debug
cargo run --quiet --manifest-path "%HERE%Cargo.toml" -- %*
exit /b %ERRORLEVEL%

:run_release
"%HERE%target\release\ai.exe" %*
exit /b %ERRORLEVEL%

:run_debug
"%HERE%target\debug\ai.exe" %*
exit /b %ERRORLEVEL%
