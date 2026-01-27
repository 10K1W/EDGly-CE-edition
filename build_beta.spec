# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for EDGY Repository Modeller Beta v0.1
Run: pyinstaller build_beta.spec --clean
"""
import os

block_cipher = None

# Prepare data files
datas = [
    ('index.html', '.'),
    ('public/images', 'public/images'),
]

# Include demo database if it exists
if os.path.exists('domainmodel.db'):
    datas.append(('domainmodel.db', '.'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'flask',
        'flask_cors',
        'sqlite3',
        'requests',
        'ddgs',
        'webview',
        'json',
        'zlib',
        'base64',
        'urllib.parse',
        'urllib.request',
        'webbrowser',
        'threading',
        'pathlib',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'tkinter',
    ],
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
    name='EDGY_Repository_Modeller_Beta_v0.1',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Set to True to show console for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico',  # Uncomment and add icon.ico file if you have one
)
