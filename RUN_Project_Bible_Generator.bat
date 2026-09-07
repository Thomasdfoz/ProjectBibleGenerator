@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo Python was not found.
    echo Install Python 3.10+ and enable "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

python project_bible_generator.py --gui

if %errorlevel% neq 0 (
    echo.
    echo Project Bible Generator exited with an error.
    pause
)
