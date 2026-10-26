@echo off
setlocal
chcp 65001 >nul 2>&1
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title Windows SuperControl
cd /d "%~dp0"

set "ARG="
if /i "%~1"=="diagnose" set "ARG=--diagnose"

where py >nul 2>&1
if %errorlevel%==0 (
    py -3 "%~dp0bootstrap.py" %ARG%
    goto :end
)

where python >nul 2>&1
if %errorlevel%==0 (
    python "%~dp0bootstrap.py" %ARG%
    goto :end
)

echo.
echo  Python 3 was NOT found. Install it from https://www.python.org/downloads/
echo  During setup tick BOTH "Add Python to PATH" and "tcl/tk and IDLE".
echo.
pause

:end
endlocal
