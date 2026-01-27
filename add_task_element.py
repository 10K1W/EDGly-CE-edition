#!/usr/bin/env python3
"""
Script to add a Task element to the database
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.getenv('DB_PATH', 'domainmodel.db')

def get_db_connection():
    """Create and return a SQLite database connection"""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def add_task_element():
    """Add Task element to the database"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Check if Task element already exists
        cur.execute('''
            SELECT id, name, enterprise, element
            FROM domainmodel
            WHERE name = ? AND enterprise = ? AND element = ?
        ''', ('Task', 'Demo', 'Task'))
        
        existing = cur.fetchone()
        
        if existing:
            print(f"Task element already exists!")
            print(f"  ID: {existing['id']}")
            print(f"  Name: {existing['name']}")
            print(f"  Enterprise: {existing['enterprise']}")
            print(f"  Element Type: {existing['element']}")
            conn.close()
            return existing['id']
        
        # Insert the new Task element
        cur.execute('''
            INSERT INTO domainmodel (name, description, enterprise, facet, element, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ''', ('Task', None, 'Demo', None, 'Task'))
        
        conn.commit()
        element_id = cur.lastrowid
        
        print("=" * 60)
        print("Task Element Added Successfully!")
        print("=" * 60)
        print(f"  ID: {element_id}")
        print(f"  Name: Task")
        print(f"  Enterprise: Demo")
        print(f"  Element Type: Task")
        print("=" * 60)
        
        cur.close()
        conn.close()
        return element_id
        
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"Error adding Task element: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == '__main__':
    add_task_element()

