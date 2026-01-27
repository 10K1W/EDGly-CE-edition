#!/usr/bin/env python3
"""Test inserting a property with NULL element_id"""

import sqlite3

DB_PATH = 'domainmodel.db'

def test_insert():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    try:
        # Test insert with NULL element_id
        cur.execute('''
            INSERT INTO domainelementproperties (element_id, propertyname, ragtype, description, image_url)
            VALUES (?, ?, ?, ?, ?)
        ''', (None, 'Test Property', 'black', 'Test Description', '/images/Tag-Black.svg'))
        
        property_id = cur.lastrowid
        conn.commit()
        
        print(f"SUCCESS: Inserted property with ID {property_id}")
        
        # Verify it was inserted correctly
        cur.execute('SELECT id, element_id, propertyname FROM domainelementproperties WHERE id = ?', (property_id,))
        row = cur.fetchone()
        print(f"  ID: {row[0]}, element_id: {row[1]}, name: {row[2]}")
        
        # Clean up test record
        cur.execute('DELETE FROM domainelementproperties WHERE id = ?', (property_id,))
        conn.commit()
        print("  Test record cleaned up")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    test_insert()

