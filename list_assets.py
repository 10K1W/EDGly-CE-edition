#!/usr/bin/env python3
"""
Script to list all Asset elements in the database
"""

import sqlite3
import os

DB_PATH = os.getenv('DB_PATH', 'domainmodel.db')

def get_db_connection():
    """Create and return a SQLite database connection"""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

def list_assets():
    """List all Asset elements"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Find all Asset elements
    cur.execute('''
        SELECT id, name, enterprise, facet, element, created_at
        FROM domainmodel
        WHERE element = 'Asset'
        ORDER BY name
    ''')
    
    records = cur.fetchall()
    
    if not records:
        print("No Asset elements found!")
    else:
        print(f"Found {len(records)} Asset element(s):")
        print("-" * 80)
        for record in records:
            print(f"ID: {record['id']} | Name: {record['name']} | Enterprise: {record['enterprise']} | Facet: {record['facet']}")
    
    conn.close()
    return records

if __name__ == '__main__':
    print("=" * 80)
    print("Listing all Asset elements")
    print("=" * 80)
    list_assets()

