#!/usr/bin/env python3
"""
Script to search for Namecheap in all fields of all elements
"""

import sqlite3
import os

DB_PATH = os.getenv('DB_PATH', 'domainmodel.db')

def get_db_connection():
    """Create and return a SQLite database connection"""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn

def search_all_fields():
    """Search for Namecheap in all fields"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Search in name, description, enterprise fields
    cur.execute('''
        SELECT id, name, enterprise, facet, element, description, created_at
        FROM domainmodel
        WHERE LOWER(name) LIKE '%namecheap%' 
           OR LOWER(description) LIKE '%namecheap%'
           OR LOWER(enterprise) LIKE '%namecheap%'
        ORDER BY id
    ''')
    
    records = cur.fetchall()
    
    if not records:
        print("No elements found with 'namecheap' in any field!")
        print("\nSearching for similar names...")
        # Try searching for similar patterns
        cur.execute('''
            SELECT id, name, enterprise, facet, element, description
            FROM domainmodel
            WHERE LOWER(name) LIKE '%name%' AND LOWER(name) LIKE '%cheap%'
            ORDER BY id
        ''')
        similar = cur.fetchall()
        if similar:
            print(f"\nFound {len(similar)} element(s) with 'name' and 'cheap' in name:")
            for rec in similar:
                print(f"  ID: {rec['id']} | Name: {rec['name']} | Element: {rec['element']}")
    else:
        print(f"Found {len(records)} element(s) with 'namecheap' in any field:")
        print("-" * 80)
        for record in records:
            print(f"ID: {record['id']}")
            print(f"  Name: {record['name']}")
            print(f"  Element Type: {record['element']}")
            print(f"  Enterprise: {record['enterprise']}")
            print(f"  Facet: {record['facet']}")
            print(f"  Description: {record['description'][:100] if record['description'] else 'N/A'}...")
            print("-" * 80)
    
    conn.close()
    return records

if __name__ == '__main__':
    print("=" * 80)
    print("Searching for Namecheap in all fields")
    print("=" * 80)
    search_all_fields()

