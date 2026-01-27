# Quick Start Guide: Building Windows Executable

## Prerequisites
- Python 3.8+ installed
- Windows 10/11
- Internet connection (for downloading dependencies)

## Database Migration

**Important**: The production app automatically copies elements and relationships from your development database (`domainmodel.db`) when creating a new production database. This happens automatically on first run if:
- The production database is empty
- A `domainmodel.db` file is found in the executable directory or script directory

To include your dev database with the executable (optional):
1. Ensure `domainmodel.db` exists in the project root
2. Optionally update `build.spec` to include it (see comments in the file)

---

## Step-by-Step Instructions

### 1. Prepare the Environment
```bash
# Run the build script (it will create venv and install everything)
build_exe.bat
```

Or manually:
```bash
# Create virtual environment
python -m venv venv_build
venv_build\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install pyinstaller
```

### 2. Build the Executable
```bash
# Using the spec file (recommended)
pyinstaller build.spec --clean

# Or quick build command
pyinstaller --onefile --console --name "EDGY_Repository_Modeller" --add-data "index.html;." --add-data "public;public" main.py
```

### 3. Test the Executable
1. Navigate to the `dist` folder
2. Double-click `EDGY_Repository_Modeller.exe`
3. Verify the application opens in your browser
4. Test key features

### 4. Distribute
- Copy `dist\EDGY_Repository_Modeller.exe` to your distribution folder
- Include README.md and USER_GUIDE.md
- Optionally create an installer using Inno Setup

## Troubleshooting

**Build fails with "ModuleNotFoundError"**
- Add the missing module to `hiddenimports` in `build.spec`

**Executable is very large**
- This is normal (50-100MB is expected)
- PyInstaller bundles Python runtime and all dependencies

**Antivirus flags the executable**
- This is common with PyInstaller executables
- Consider code signing (requires certificate)
- Provide checksums for users to verify

**Database not found**
- The executable creates database in: `%APPDATA%\EDGY_Repository_Modeller\`
- Check that directory exists and is writable

## Next Steps
See `PRODUCTION_BUILD_PLAN.md` for detailed information and advanced options.

