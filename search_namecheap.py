#!/usr/bin/env python3
"""
Script to search for Namecheap-related elements in the database
"""

import sqlite3
import os

DB_PATH = os.getenv('DB_PATH', 'domainmodel.db')

def get_db_connection():
    """Create and return a SQLite database connection"""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

def search_namecheap():
    """Search for any Namecheap-related elements"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Search for any element with Namecheap in the name
    cur.execute('''
        SELECT id, name, enterprise, facet, element, created_at
        FROM domainmodel
        WHERE name LIKE '%Namecheap%' OR name LIKE '%namecheap%'
        ORDER BY id
    ''')
    
    records = cur.fetchall()
    
    if not records:
        print("No Namecheap-related elements found!")
    else:
        print(f"Found {len(records)} Namecheap-related element(s):")
        print("-" * 80)
        for record in records:
            print(f"ID: {record['id']}")
            print(f"  Name: {record['name']}")
            print(f"  Element Type: {record['element']}")
            print(f"  Enterprise: {record['enterprise']}")
            print(f"  Facet: {record['facet']}")
            print(f"  Created: {record['created_at']}")
            print("-" * 80)
    
    conn.close()
    return records

if __name__ == '__main__':
    print("=" * 80)
    print("Searching for Namecheap-related elements")
    print("=" * 80)
    search_namecheap()

