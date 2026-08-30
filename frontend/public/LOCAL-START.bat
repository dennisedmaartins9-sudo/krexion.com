@echo off
REM Always run the repo-root installer (avoid stale copies in public/build).
cd /d "%~dp0..\.."
call "%~dp0..\..\LOCAL-START.bat" %*
