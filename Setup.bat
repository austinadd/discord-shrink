@echo off
rem One-time setup: installs Python, Pillow and ffmpeg if they're missing (from the official winget catalog).
title Discord Shrink setup
cd /d "%~dp0"

call :findpy
if not defined PY (
    echo Installing Python...
    winget install --id Python.Python.3.13 -e --scope user --accept-source-agreements --accept-package-agreements
    call :findpy
)
if not defined PY (
    echo.
    echo Couldn't find Python after installing it. Close this window and run Setup.bat again.
    pause
    exit /b 1
)

echo Installing Pillow (for images)...
"%PY%" -m pip install --user --upgrade pillow

where ffmpeg >nul 2>nul || if not exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe" (
    echo Installing ffmpeg (for videos)...
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
)

echo.
echo All set! Double-click "Discord Shrink.bat" to start.
pause
exit /b 0

:findpy
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Launcher\py.exe"
if not defined PY for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
exit /b 0
