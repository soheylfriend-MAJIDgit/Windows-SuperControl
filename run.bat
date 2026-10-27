@echo off
rem ===========================================================
rem  Windows SuperControl - compatibility launcher
rem  The real launcher is run.vbs (100% no console window).
rem  This .bat just hands off to it and exits immediately.
rem  Use "run.bat diagnose" only when you WANT a console + logs.
rem ===========================================================
setlocal
cd /d "%~dp0"

if /I "%~1"=="diagnose" goto diagnose
if /I "%~1"=="install" goto install

start "" wscript.exe //B //Nologo "%~dp0run.vbs"
exit /b 0

:install
echo Installing pywebview (optional - browser fallback works without it)...
py -3 -m pip install --user pywebview 2>nul || python -m pip install --user pywebview
echo.
echo Done. Now double-click run.vbs (or run.bat).
pause
exit /b 0

:diagnose
echo.
echo === Windows SuperControl - diagnose ===
py -3 -u "%~dp0bootstrap.py" --diagnose 2>nul || python -u "%~dp0bootstrap.py" --diagnose
echo.
pause
exit /b 0
