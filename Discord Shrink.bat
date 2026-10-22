@echo off
rem Double-click to open the window, or drag files onto this icon to shrink them straight away.
set "PY="
set "PYW="
where py >nul 2>nul && (set "PY=py" & set "PYW=pyw")
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" (
    set "PY=%LOCALAPPDATA%\Programs\Python\Launcher\py.exe"
    set "PYW=%LOCALAPPDATA%\Programs\Python\Launcher\pyw.exe"
)
if not defined PY for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" (
    set "PY=%%D\python.exe"
    set "PYW=%%D\pythonw.exe"
)
if not defined PY (
    echo Python isn't installed yet. Run Setup.bat first.
    pause
    exit /b 1
)
if "%~1"=="" (
    start "" "%PYW%" "%~dp0discord_shrink.py"
    exit /b
)
"%PY%" "%~dp0discord_shrink.py" %*
echo.
pause
