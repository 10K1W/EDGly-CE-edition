# DomainModel Records Manager - Standalone Version

A simple, standalone web UI for managing records in your Neon database DomainModel table.

## Quick Start

### Option 1: Double-click to run (Windows)
1. Double-click `start.bat`
2. The server will start automatically
3. Open your browser to: http://localhost:5000

### Option 2: Manual start
1. Open PowerShell or Command Prompt in this folder
2. Install dependencies:
   ```bash
   pip install flask psycopg2-binary flask-cors
   ```
3. Start the server:
   ```bash
   python server.py
   ```
4. Open your browser to: http://localhost:5000

## Requirements

- **Python 3.6 or higher** (usually pre-installed on Windows)
  - If not installed, download from: https://www.python.org/
  - Make sure to check "Add Python to PATH" during installation

## Features

- ✅ Add new records with all fields (name, description, enterprise, facet, element)
- ✅ View all existing records
- ✅ Delete records
- ✅ Modern, responsive UI
- ✅ Real-time feedback

## Files

- `server.py` - Python Flask server
- `index.html` - Web interface
- `start.bat` - Quick start script for Windows
- `requirements.txt` - Python dependencies

## Database Connection

The database connection is already configured in `server.py` with your Neon credentials. No additional configuration needed!

## Troubleshooting

**"Python is not recognized"**
- Install Python from https://www.python.org/
- Make sure to check "Add Python to PATH" during installation
- Restart your terminal after installation

**"pip is not recognized"**
- Python should include pip. Try: `python -m pip install flask psycopg2-binary flask-cors`

**Port 5000 already in use**
- Edit `server.py` and change `port=5000` to a different port (e.g., `port=5001`)
- Then access: http://localhost:5001

**Database connection errors**
- Check your internet connection
- Verify the database connection string in `server.py`

