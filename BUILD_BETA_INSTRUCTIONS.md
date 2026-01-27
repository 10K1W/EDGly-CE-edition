# Building EDGY Repository Modeller Beta v0.1

## Overview

This document explains how to build the Windows EXE installer for EDGY Repository Modeller Beta v0.1. The build process creates a standalone executable that includes:
- All Python dependencies (bundled by PyInstaller)
- Demo Enterprise database with sample data
- All application files
- A Windows installer for easy installation

## Prerequisites

- **Windows 10/11** (64-bit)
- **Python 3.8+** installed (for building only - users don't need Python)
- **Internet connection** (for downloading dependencies)

## Build Process

### Step 1: Prepare the Build Environment

1. Open Command Prompt or PowerShell
2. Navigate to the project directory:
   ```
   cd C:\Users\matth\EDGY_RepoModeller
   ```

### Step 2: Run the Build Script

Run the build script:
```
build_beta_v0.1.bat
```

This script will:
1. Create/use virtual environment (`venv_build`)
2. Install all dependencies (Flask, PyInstaller, etc.)
3. Prepare the Demo Enterprise database (filters to Demo enterprise only)
4. Build the Windows EXE using PyInstaller
5. Output: `dist\EDGY_Repository_Modeller_Beta_v0.1.exe`

### Step 3: Create the Installer (Optional but Recommended)

1. **Download Inno Setup** (if not already installed):
   - Visit: https://jrsoftware.org/isinfo.php
   - Download and install Inno Setup Compiler

2. **Compile the installer**:
   - Open Inno Setup Compiler
   - Open `setup_beta_v0.1.iss`
   - Click "Build" → "Compile"
   - Output: `installer\EDGY_Repository_Modeller_Beta_v0.1_Setup.exe`

### Step 4: Test the Build

1. **Test the EXE** (without installer):
   - Navigate to `dist\` folder
   - Double-click `EDGY_Repository_Modeller_Beta_v0.1.exe`
   - Verify the application starts and opens in browser
   - Check that Demo Enterprise data is present

2. **Test the installer** (recommended):
   - Run `installer\EDGY_Repository_Modeller_Beta_v0.1_Setup.exe`
   - Install on a clean system (or VM)
   - Verify installation
   - Test the application

## Distribution Package

The distribution package should include:

1. **Installer**: `EDGY_Repository_Modeller_Beta_v0.1_Setup.exe`
2. **README**: `README_BETA.md`
3. **Documentation**: Any additional user guides

### Optional Files:
- Standalone EXE: `EDGY_Repository_Modeller_Beta_v0.1.exe` (for advanced users)
- CHANGELOG.md (if available)
- LICENSE file

## What's Included

### Application Files
- `EDGY_Repository_Modeller_Beta_v0.1.exe` - Standalone executable
- `index.html` - Main UI
- `public/images/` - All image assets

### Database
- Demo Enterprise data only
- Filtered to include only elements, relationships, and properties for Demo enterprise
- Database is created in user's AppData on first run

### Dependencies (Bundled in EXE)
- Python runtime (bundled by PyInstaller)
- Flask web framework
- Flask-CORS
- Requests library
- DuckDuckGo Search (ddgs)
- SQLite (built into Python)
- All other required packages

## Important Notes

### Python Not Required for End Users
- PyInstaller bundles Python and all dependencies into the EXE
- End users do NOT need Python installed
- The EXE is completely standalone

### Database Location
- Development: `domainmodel.db` in project directory
- Production: `%APPDATA%\EDGY_Repository_Modeller\domainmodel.db`
- Demo data is initialized on first run (if database is empty)

### Version Information
- Version: Beta v0.1
- Displayed in: Application title, installer, README

## Troubleshooting Build Issues

### Build Fails with ModuleNotFoundError
- Add missing module to `hiddenimports` in `build_beta.spec`
- Re-run the build script

### Database Preparation Fails
- Check that `domainmodel.db` exists
- Verify Demo enterprise exists in the database
- Check `prepare_demo_database.py` output for errors

### Installer Creation Fails
- Verify Inno Setup is installed
- Check that `dist\EDGY_Repository_Modeller_Beta_v0.1.exe` exists
- Review Inno Setup compiler output for errors

### EXE is Very Large
- This is normal (50-150MB is expected)
- PyInstaller bundles Python runtime and all dependencies
- Compression can reduce size but increases build time

## Next Steps

1. **Test thoroughly** on clean Windows systems
2. **Create release notes** for Beta v0.1
3. **Package distribution files** for distribution
4. **Distribute to users** with installation instructions

## Support

For build issues:
- Check PyInstaller documentation
- Review build output for errors
- Check Inno Setup compiler output

For user support:
- See `README_BETA.md` for installation and troubleshooting
