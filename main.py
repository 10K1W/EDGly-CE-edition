#!/usr/bin/env python3
"""
Main entry point for EDGY Repository Modeller
Handles application initialization and startup for both development and production builds
"""
import sys
import os
import webbrowser
import threading
import time
import logging
from pathlib import Path

# Add the application directory to the path
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    application_path = sys._MEIPASS
    # Database should be in user's AppData directory
    app_data = os.path.join(os.getenv('APPDATA'), 'EDGY_Repository_Modeller')
    os.makedirs(app_data, exist_ok=True)
    os.environ['DB_PATH'] = os.path.join(app_data, 'domainmodel.db')
else:
    # Running as script
    application_path = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, application_path)

def setup_logging():
    """Configure file logging early so startup failures are captured."""
    base_dir = os.getenv('APPDATA') or os.getcwd()
    log_dir = os.path.join(base_dir, 'EDGY_Repository_Modeller', 'logs')
    log_path = os.path.join(log_dir, 'edgy_startup.log')
    try:
        os.makedirs(log_dir, exist_ok=True)
        handlers = [
            logging.FileHandler(log_path, encoding='utf-8'),
            logging.StreamHandler()
        ]
    except Exception:
        handlers = [logging.StreamHandler()]
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=handlers
    )
    logging.info("Logging initialized: %s", log_path)

setup_logging()

# Import server after path is set
try:
    from server import app, init_database, DB_PATH
except ImportError as e:
    print(f"ERROR: Failed to import server module: {e}")
    print(f"Application path: {application_path}")
    logging.exception("Failed to import server module")
    input("Press Enter to exit...")
    sys.exit(1)

try:
    import webview
    HAS_WEBVIEW = True
except Exception:
    HAS_WEBVIEW = False


def open_browser():
    """Open the default web browser after a short delay"""
    time.sleep(1.5)
    try:
        webbrowser.open('http://127.0.0.1:5000')
    except Exception as e:
        print(f"Warning: Could not open browser automatically: {e}")
        print("Please manually open http://127.0.0.1:5000 in your browser")


def run_server():
    """Run Flask server without reloader."""
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)

def main():
    """Main application entry point"""
    # Ensure database is initialized
    print("Initializing database...")
    logging.info("Initializing database...")
    if not init_database():
        print("ERROR: Failed to initialize database!")
        print(f"Database path: {DB_PATH}")
        logging.error("Failed to initialize database! DB_PATH=%s", DB_PATH)
        input("Press Enter to exit...")
        sys.exit(1)
    
    # Print startup information
    print("=" * 60)
    print("EDGY Repository Modeller - Beta v0.1")
    print("=" * 60)
    print(f"Database: {DB_PATH}")
    print(f"Starting server on http://127.0.0.1:5000")
    logging.info("Database: %s", DB_PATH)
    logging.info("Starting server on http://127.0.0.1:5000")
    print("=" * 60)
    print("\nThe application will open in your default browser.")
    print("Press Ctrl+C to stop the server.\n")
    
    if HAS_WEBVIEW:
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        time.sleep(1.0)
        try:
            webview.create_window(
                "EDGY Repository Modeller",
                "http://127.0.0.1:5000",
                width=1400,
                height=900,
                resizable=True
            )
            webview.start()
        except Exception as e:
            print(f"\nERROR: Failed to start webview window: {e}")
            logging.exception("Failed to start webview window")
            input("Press Enter to exit...")
            sys.exit(1)
    else:
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
        except Exception as e:
            print(f"\nERROR: Server failed to start: {e}")
            logging.exception("Server failed to start")
            import traceback
            traceback.print_exc()
            input("Press Enter to exit...")
            sys.exit(1)

if __name__ == '__main__':
    main()

