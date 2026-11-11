@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher was not found. Install Python 3.11 or newer first.
    pause
    exit /b 1
)

echo [1/3] Creating desktop virtual environment...
py -3.11 -m venv desktop\.venv
if errorlevel 1 (
    echo Failed to create the virtual environment. Check that Python 3.11 is installed.
    pause
    exit /b 1
)

echo [2/3] Installing FunPay Assistant Desktop...
call desktop\.venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :failed
python -m pip install -e desktop
if errorlevel 1 goto :failed

echo [3/3] Installation completed.
echo.
echo Next:
echo  1. Run Start.bat once to complete the original Vertex setup.
echo  2. Then launch RunDesktop.bat to open FunPay Assistant.
echo.
pause
exit /b 0

:failed
echo.
echo Installation failed. Read the error above.
pause
exit /b 1
