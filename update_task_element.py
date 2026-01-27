#!/usr/bin/env python3
"""
Script to update Task element with image and Experience facet
"""

import sqlite3
import os

DB_PATH = os.getenv('DB_PATH', 'domainmodel.db')

def get_db_connection():
    """Create and return a SQLite database connection"""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def update_task_element():
    """Update Task element with image_url and Experience facet"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Find the Task element
        cur.execute('''
            SELECT id, name, enterprise, element, facet, image_url
            FROM domainmodel
            WHERE name = ? AND enterprise = ? AND element = ?
        ''', ('Task', 'Demo', 'Task'))
        
        task = cur.fetchone()
        
        if not task:
            print("Task element not found!")
            conn.close()
            return False
        
        print(f"Found Task element:")
        print(f"  ID: {task['id']}")
        print(f"  Current Facet: {task['facet']}")
        print(f"  Current Image URL: {task['image_url']}")
        
        # Update the Task element
        cur.execute('''
            UPDATE domainmodel
            SET facet = ?, image_url = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', ('Experience', '/images/Shape-Task.svg', task['id']))
        
        conn.commit()
        
        # Verify the update
        cur.execute('''
            SELECT id, name, enterprise, element, facet, image_url
            FROM domainmodel
            WHERE id = ?
        ''', (task['id'],))
        
        updated = cur.fetchone()
        
        print("\n" + "=" * 60)
        print("Task Element Updated Successfully!")
        print("=" * 60)
        print(f"  ID: {updated['id']}")
        print(f"  Name: {updated['name']}")
        print(f"  Enterprise: {updated['enterprise']}")
        print(f"  Element Type: {updated['element']}")
        print(f"  Facet: {updated['facet']}")
        print(f"  Image URL: {updated['image_url']}")
        print("=" * 60)
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"Error updating Task element: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    update_task_element()

