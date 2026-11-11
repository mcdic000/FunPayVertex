@echo off
setlocal
cd /d "%~dp0"

if not exist "desktop\.venv\Scripts\activate.bat" (
    echo FunPay Assistant is not installed yet.
    echo Run InstallDesktop.bat first.
    pause
    exit /b 1
)

call "desktop\.venv\Scripts\activate.bat"
cd /d "%~dp0desktop"
python -m desktop
if errorlevel 1 (
    echo.
    echo FunPay Assistant closed with an error.
    pause
)
