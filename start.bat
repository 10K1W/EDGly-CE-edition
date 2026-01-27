@echo off
echo Checking for Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo Python is not installed or not in PATH.
    echo Please install Python from https://www.python.org/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo Python found!
echo.
echo Installing required packages...
pip install -q -r requirements.txt

echo.
echo Starting app...
echo The app will open in its own window.
echo.
echo Press Ctrl+C to stop the server
echo.

python main.py

