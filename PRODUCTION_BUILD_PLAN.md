# Production Build Plan: Windows Executable Distribution

## Overview
This document outlines a comprehensive plan to convert the EDGY Repository Modeller Flask application into a production-ready, distributable Windows executable (.exe) file.

## Recommended Approach: PyInstaller

**PyInstaller** is the most popular and reliable tool for creating Windows executables from Python applications. It bundles Python, your code, and all dependencies into a single executable file.

---

## Database Migration Feature

**NEW**: The production app now automatically copies elements and relationships from the development database (`domainmodel.db`) when creating a new production database. This ensures that all your existing data is available in the production version.

### How It Works:
1. When the production app initializes a new database (first run), it checks if the database is empty
2. If empty, it searches for `domainmodel.db` in:
   - The executable directory (if running as .exe)
   - The script directory (if running as script)
   - The current working directory
3. If found, it copies:
   - All elements from `domainmodel` table
   - All relationships from `domainmodelrelationship` table
   - All properties from `domainelementproperties` table
4. ID mappings are preserved to maintain referential integrity

### To Include Dev Database in Distribution:
If you want to include the development database with the executable (optional):
1. Copy `domainmodel.db` to the same directory as the executable
2. The production app will automatically detect and use it on first run

---

## Phase 1: Preparation & Setup

### 1.1 Environment Setup
```bash
# Create a clean virtual environment
python -m venv venv_build
venv_build\Scripts\activate

# Install all dependencies
pip install -r requirements.txt

# Install PyInstaller
pip install pyinstaller
```

### 1.2 Create Entry Point Script
Create a new file `main.py` that will serve as the entry point:

```python
#!/usr/bin/env python3
"""
Main entry point for EDGY Repository Modeller
Handles application initialization and startup
"""
import sys
import os
import webbrowser
import threading
import time
from pathlib import Path

# Add the application directory to the path
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    application_path = sys._MEIPASS
else:
    # Running as script
    application_path = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, application_path)

# Import server after path is set
from server import app, init_database, DB_PATH

def open_browser():
    """Open the default web browser after a short delay"""
    time.sleep(1.5)
    webbrowser.open('http://127.0.0.1:5000')

def main():
    """Main application entry point"""
    # Ensure database is initialized
    if not init_database():
        print("ERROR: Failed to initialize database!")
        input("Press Enter to exit...")
        sys.exit(1)
    
    # Print startup information
    print("=" * 60)
    print("EDGY Repository Modeller")
    print("=" * 60)
    print(f"Database: {DB_PATH}")
    print(f"Starting server on http://127.0.0.1:5000")
    print("=" * 60)
    print("\nThe application will open in your default browser.")
    print("Press Ctrl+C to stop the server.\n")
    
    # Open browser in a separate thread
    browser_thread = threading.Thread(target=open_browser)
    browser_thread.daemon = True
    browser_thread.start()
    
    # Run the Flask app
    try:
        app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print("\n\nShutting down server...")
        sys.exit(0)

if __name__ == '__main__':
    main()
```

### 1.3 Create PyInstaller Spec File
Create `build.spec` for advanced configuration:

```python
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('index.html', '.'),
        ('public/images', 'public/images'),
        ('domainmodel.db', '.'),  # Include database template (optional)
    ],
    hiddenimports=[
        'flask',
        'flask_cors',
        'sqlite3',
        'requests',
        'ddgs',
        'json',
        'zlib',
        'base64',
        'urllib.parse',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='EDGY_Repository_Modeller',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Set to False to hide console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',  # Optional: Add application icon
)
```

---

## Phase 2: Build Configuration

### 2.1 Database Path Handling
Update `server.py` to handle database location in executable:

```python
import sys
import os

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)

# Update DB_PATH to use user's AppData directory for production
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    app_data = os.path.join(os.getenv('APPDATA'), 'EDGY_Repository_Modeller')
    os.makedirs(app_data, exist_ok=True)
    DB_PATH = os.path.join(app_data, 'domainmodel.db')
else:
    # Running as script
    DB_PATH = os.getenv('DB_PATH', 'domainmodel.db')
```

### 2.2 Static Files Handling
Ensure Flask can find static files:

```python
# In server.py, update Flask initialization
if getattr(sys, 'frozen', False):
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    static_folder = os.path.join(sys._MEIPASS, 'static')
    app = Flask(__name__, 
                template_folder=template_folder,
                static_folder=static_folder)
else:
    app = Flask(__name__, static_folder='.')
```

### 2.3 Create Build Script
Create `build_exe.bat`:

```batch
@echo off
echo Building EDGY Repository Modeller Executable...
echo.

REM Activate virtual environment
call venv_build\Scripts\activate.bat

REM Clean previous builds
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__

REM Build executable
pyinstaller build.spec --clean

echo.
echo Build complete! Executable is in the 'dist' folder.
echo.
pause
```

---

## Phase 3: Testing & Validation

### 3.1 Test Checklist
- [ ] Executable launches without errors
- [ ] Database initializes correctly
- [ ] Web interface loads in browser
- [ ] All images/assets load correctly
- [ ] API endpoints respond correctly
- [ ] Database operations (CRUD) work
- [ ] File paths resolve correctly
- [ ] No console errors or warnings

### 3.2 Test on Clean Windows Machine
Test the executable on a Windows machine without Python installed to ensure all dependencies are bundled.

---

## Phase 4: Distribution Preparation

### 4.1 Create Installer (Optional but Recommended)
Use **Inno Setup** (free, open-source) to create a professional installer:

1. Download Inno Setup: https://jrsoftware.org/isinfo.php
2. Create `setup.iss` script:

```ini
[Setup]
AppName=EDGY Repository Modeller
AppVersion=1.0.0
DefaultDirName={pf}\EDGY Repository Modeller
DefaultGroupName=EDGY Repository Modeller
OutputDir=installer
OutputBaseFilename=EDGY_Repository_Modeller_Setup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin

[Files]
Source: "dist\EDGY_Repository_Modeller.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\EDGY Repository Modeller"; Filename: "{app}\EDGY_Repository_Modeller.exe"
Name: "{group}\Uninstall"; Filename: "{uninstallexe}"
Name: "{commondesktop}\EDGY Repository Modeller"; Filename: "{app}\EDGY_Repository_Modeller.exe"

[Run]
Filename: "{app}\EDGY_Repository_Modeller.exe"; Description: "Launch EDGY Repository Modeller"; Flags: nowait postinstall skipifsilent
```

### 4.2 Create Application Icon
- Create or obtain a `.ico` file (256x256 recommended)
- Place it in the project root as `icon.ico`
- Update `build.spec` to reference it

### 4.3 Documentation
Create `USER_GUIDE.md` with:
- Installation instructions
- System requirements
- First-time setup
- Troubleshooting guide
- Uninstallation instructions

---

## Phase 5: Advanced Features (Optional)

### 5.1 Auto-Updater
Consider implementing an auto-update mechanism:
- Check for updates on startup
- Download new version if available
- Prompt user to update

### 5.2 Logging
Add comprehensive logging:
```python
import logging
import os

if getattr(sys, 'frozen', False):
    log_dir = os.path.join(os.getenv('APPDATA'), 'EDGY_Repository_Modeller', 'logs')
else:
    log_dir = 'logs'

os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(log_dir, 'app.log'),
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### 5.3 Error Reporting
Implement error reporting:
- Catch unhandled exceptions
- Log to file
- Optionally send to remote server (with user consent)

### 5.4 System Tray Integration
Use `pystray` to add system tray icon:
```python
import pystray
from PIL import Image

def create_tray_icon():
    image = Image.open("icon.png")
    menu = pystray.Menu(
        pystray.MenuItem("Open", open_app),
        pystray.MenuItem("Quit", quit_app)
    )
    icon = pystray.Icon("EDGY", image, "EDGY Repository Modeller", menu)
    icon.run()
```

---

## Phase 6: Build Commands

### Quick Build (One-File Executable)
```bash
pyinstaller --onefile --windowed --name "EDGY_Repository_Modeller" --add-data "index.html;." --add-data "public;public" main.py
```

### Advanced Build (Using Spec File)
```bash
pyinstaller build.spec --clean
```

### Build Options Explained
- `--onefile`: Creates a single executable file
- `--windowed`: Hides console window (use `--console` to show it)
- `--name`: Sets the executable name
- `--add-data`: Includes additional files/directories
- `--icon`: Sets the application icon
- `--clean`: Cleans PyInstaller cache before building

---

## Phase 7: Distribution Checklist

### Pre-Release
- [ ] Code is production-ready (no debug code)
- [ ] All dependencies are included
- [ ] Database initializes correctly
- [ ] All features tested
- [ ] Documentation complete
- [ ] Version number set
- [ ] License file included

### Release Package
- [ ] Executable file (.exe)
- [ ] Installer (optional)
- [ ] README.md
- [ ] USER_GUIDE.md
- [ ] LICENSE file
- [ ] CHANGELOG.md

### Post-Release
- [ ] Test installer on clean Windows VM
- [ ] Verify all features work
- [ ] Create release notes
- [ ] Upload to distribution platform

---

## Alternative Approaches

### Option 1: PyInstaller (Recommended)
**Pros:**
- Most popular and well-documented
- Good Windows support
- Single executable option
- Active community

**Cons:**
- Larger file size
- Slower startup time
- Antivirus false positives (common)

### Option 2: cx_Freeze
**Pros:**
- Cross-platform
- Good documentation
- Smaller file size

**Cons:**
- More complex setup
- Less popular than PyInstaller

### Option 3: Nuitka
**Pros:**
- Compiles to C++ (faster)
- Smaller executables
- Better performance

**Cons:**
- Requires C++ compiler
- Longer build times
- More complex setup

### Option 4: Electron Wrapper
**Pros:**
- Native desktop feel
- Easy distribution
- Auto-updater built-in

**Cons:**
- Very large file size (~100MB+)
- Requires Node.js knowledge
- More complex architecture

---

## Recommended File Structure

```
EDGY_RepoModeller/
├── main.py                 # Entry point
├── server.py              # Flask application
├── index.html             # Frontend
├── build.spec             # PyInstaller spec
├── build_exe.bat          # Build script
├── setup.iss              # Inno Setup script
├── icon.ico               # Application icon
├── requirements.txt        # Python dependencies
├── README.md              # Project documentation
├── USER_GUIDE.md          # User documentation
├── PRODUCTION_BUILD_PLAN.md  # This file
├── public/                # Static assets
│   └── images/
└── dist/                  # Build output (generated)
    └── EDGY_Repository_Modeller.exe
```

---

## Estimated File Sizes

- **Single executable**: ~50-100 MB (includes Python runtime)
- **With installer**: ~60-110 MB
- **Uncompressed**: ~200-300 MB

---

## System Requirements

- **OS**: Windows 7 or later (64-bit recommended)
- **RAM**: 2 GB minimum, 4 GB recommended
- **Disk Space**: 500 MB for installation
- **Network**: Required for web search features (optional)

---

## Next Steps

1. **Immediate**: Create `main.py` entry point
2. **Short-term**: Set up PyInstaller and create first build
3. **Medium-term**: Test thoroughly and fix any issues
4. **Long-term**: Create installer and distribution package

---

## Troubleshooting Common Issues

### Issue: "Failed to execute script"
**Solution**: Check that all dependencies are included in `hiddenimports`

### Issue: Images/assets not loading
**Solution**: Ensure files are included in `datas` section of spec file

### Issue: Database not found
**Solution**: Update database path to use user's AppData directory

### Issue: Antivirus flags executable
**Solution**: 
- Code sign the executable (requires certificate)
- Submit to antivirus vendors for whitelisting
- Provide checksums for verification

### Issue: Large file size
**Solution**: 
- Use `--exclude-module` to exclude unused modules
- Consider UPX compression (already enabled in spec)
- Use `--onedir` instead of `--onefile` (smaller but multiple files)

---

## Additional Resources

- PyInstaller Documentation: https://pyinstaller.org/
- Inno Setup Documentation: https://jrsoftware.org/ishelp/
- Python Packaging Guide: https://packaging.python.org/

---

## Version History

- **v1.0** - Initial production build plan

