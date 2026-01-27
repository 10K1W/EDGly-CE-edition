# EDGY Repository Modeller - Beta v0.1

## Installation

### Quick Install (Recommended for Non-Technical Users)

1. **Download the installer**: `EDGY_Repository_Modeller_Beta_v0.1_Setup.exe`
2. **Double-click the installer** to run it
3. **Follow the installation wizard**:
   - Click "Next" on the welcome screen
   - Choose an installation location (default is recommended)
   - Click "Install" to begin installation
   - Click "Finish" when installation is complete
4. **Launch the application**:
   - The application will start automatically after installation
   - Or use the desktop shortcut or Start Menu entry

### Manual Installation (Advanced Users)

If you prefer not to use the installer:

1. Extract `EDGY_Repository_Modeller_Beta_v0.1.exe` to a folder
2. Double-click the `.exe` file to run the application
3. The application will create its data folder in: `%APPDATA%\EDGY_Repository_Modeller\`

## System Requirements

- **Operating System**: Windows 10 or Windows 11 (64-bit)
- **RAM**: Minimum 4GB, Recommended 8GB
- **Disk Space**: 200MB for installation
- **Internet Connection**: Required for chatbot features (Google Gemini API)
- **Browser**: Any modern web browser (Chrome, Firefox, Edge, etc.)

**Note**: Python is NOT required - it is bundled with the application.

## First Run

1. The application will start a local web server
2. Your default web browser will open automatically
3. If the browser doesn't open, navigate to: `http://127.0.0.1:5000`
4. The application includes Demo Enterprise data for testing

## Features

This beta version includes:
- Repository element management
- Relationship modeling
- EDGY Enterprise Design templates (Milkyway Map, Service Blueprint)
- EDGly AI chatbot assistant
- Canvas-based modeling interface
- Property management
- Diagram generation

## Data

This beta version includes **Demo Enterprise** data only:
- Sample elements from the Demo enterprise
- Sample relationships
- Sample properties

All data is stored locally in: `%APPDATA%\EDGY_Repository_Modeller\domainmodel.db`

## Troubleshooting

### Application Won't Start

1. Check Windows Firewall - it may block the application
2. Check if port 5000 is already in use
3. Try running as Administrator (right-click → Run as Administrator)
4. Check Windows Event Viewer for error messages

### Browser Doesn't Open Automatically

1. Manually open your web browser
2. Navigate to: `http://127.0.0.1:5000`
3. The application is still running if you see the console window

### Database Errors

1. The database is created automatically on first run
2. If you see database errors, delete the database folder:
   - Go to: `%APPDATA%\EDGY_Repository_Modeller\`
   - Delete `domainmodel.db`
   - Restart the application

### Port Already in Use

If port 5000 is already in use:
1. Close other applications using port 5000
2. Or restart your computer
3. The application will fail to start if the port is unavailable

## Uninstallation

### Using the Installer

1. Go to: Settings → Apps → Apps & features
2. Find "EDGY Repository Modeller"
3. Click "Uninstall"
4. Follow the uninstallation wizard

### Manual Uninstallation

1. Delete the installation folder (default: `C:\Program Files\EDGY Repository Modeller\`)
2. Delete the data folder: `%APPDATA%\EDGY_Repository_Modeller\`
3. Delete desktop shortcuts and Start Menu entries

## Support

For issues or questions:
- Check the troubleshooting section above
- Review application logs in: `%APPDATA%\EDGY_Repository_Modeller\logs\` (if available)

## Version Information

- **Version**: Beta v0.1
- **Build Date**: See installer or application
- **Python Version**: Bundled (3.x)
- **Database**: SQLite (local)

## License

See LICENSE file for license information.

## Notes

- This is a **beta version** - some features may be incomplete or have bugs
- The application runs locally - no data is sent to external servers except for:
  - Chatbot queries (Google Gemini API)
  - Web search results (DuckDuckGo)
- The application uses port 5000 by default
- All data is stored locally in SQLite database
