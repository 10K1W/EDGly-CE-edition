#!/usr/bin/env python3
"""
Script to create Process -> Process flow relationship via API endpoint
"""

import requests
import json

def create_process_flow_via_api():
    """Create Process -> Process flow relationship using the API"""
    try:
        # Call the initialization endpoint
        response = requests.post('http://localhost:5000/api/canvas/init-process-flow')
        
        if response.status_code == 200:
            result = response.json()
            print("Success! API Response:")
            print(json.dumps(result, indent=2))
            return True
        else:
            print(f"Error: HTTP {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to server.")
        print("Please make sure the Flask server is running on http://localhost:5000")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == '__main__':
    print("Creating Process -> Process flow relationship via API...")
    print("=" * 60)
    success = create_process_flow_via_api()
    print("=" * 60)
    if success:
        print("\nProcess flow relationship created successfully!")
        print("   Refresh your browser to see Process in the context menu.")
    else:
        print("\nFailed to create Process flow relationship.")
        print("   Please check the error messages above.")

