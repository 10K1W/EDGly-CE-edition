@echo off
echo ========================================
echo Building EDGY Repository Modeller
echo ========================================
echo.

REM Check if virtual environment exists
if not exist "venv_build" (
    echo Creating virtual environment...
    python -m venv venv_build
    echo.
)

REM Activate virtual environment
echo Activating virtual environment...
call venv_build\Scripts\activate.bat

REM Install/upgrade dependencies
echo Installing dependencies...
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo.
echo Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__

echo.
echo Building executable...
pyinstaller build.spec --clean

echo.
echo ========================================
if exist "dist\EDGY_Repository_Modeller.exe" (
    echo Build SUCCESSFUL!
    echo Executable location: dist\EDGY_Repository_Modeller.exe
) else (
    echo Build FAILED!
    echo Check the output above for errors.
)
echo ========================================
echo.
pause

