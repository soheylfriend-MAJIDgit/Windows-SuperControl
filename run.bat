@echo off
setlocal
chcp 65001 >nul 2>&1
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title Windows SuperControl
cd /d "%~dp0"

echo ==========================================================
echo.
echo      Windows SuperControl  -  Remote Python Launcher
echo.
echo ==========================================================
echo.
echo    Repo : %~dp0
echo.
echo    [1]  Open control panel  (fetch + run code from Drive)
echo    [0]  Exit
echo.
choice /c 10 /n /m "Your choice [1/0]: "
if errorlevel 2 goto :end

echo.
where py >nul 2>&1
if %errorlevel%==0 (
    py -3 "%~dp0launcher.py"
    goto :end
)

where python >nul 2>&1
if %errorlevel%==0 (
    python "%~dp0launcher.py"
    goto :end
)

echo.
echo  Python was NOT found on this computer.
echo  Install it from: https://www.python.org/downloads/
echo  During setup tick BOTH: "Add Python to PATH" and "tcl/tk and IDLE".
echo.
pause

:end
endlocal
