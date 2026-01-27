@echo off
REM Build script for EDGY Repository Modeller Beta v0.1
REM This script prepares the Demo Enterprise database and builds the Windows EXE

echo ========================================
echo Building EDGY Repository Modeller
echo Beta v0.1
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
echo Preparing Demo Enterprise database...
python prepare_demo_database.py

if not exist "domainmodel_demo.db" (
    echo ERROR: Failed to create demo database!
    pause
    exit /b 1
)

echo.
echo Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__

REM Copy demo database to be included in build
copy domainmodel_demo.db domainmodel.db /Y >nul

echo.
echo Building executable...
pyinstaller build_beta.spec --clean

echo.
echo ========================================
if exist "dist\EDGY_Repository_Modeller_Beta_v0.1.exe" (
    echo Build SUCCESSFUL!
    echo Executable location: dist\EDGY_Repository_Modeller_Beta_v0.1.exe
    echo.
    echo The executable is ready for distribution.
    echo You can create an installer using the setup.iss script.
) else (
    echo Build FAILED!
    echo Check the output above for errors.
)
echo ========================================
echo.
pause
