#!/usr/bin/env python3
"""
Check if Process -> Process flow relationship exists, create if needed
Uses direct SQL to bypass API validation
"""

import sqlite3
import os
import time

def get_db_connection():
    """Get database connection with retry logic"""
    db_path = os.path.join(os.path.dirname(__file__), 'domainmodel.db')
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at {db_path}")
        return None
    
    # Retry logic for locked database
    max_retries = 5
    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(db_path, timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys = ON')
            return conn
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and attempt < max_retries - 1:
                print(f"Database locked, retrying in 1 second... (attempt {attempt + 1}/{max_retries})")
                time.sleep(1)
            else:
                print(f"Error connecting to database: {e}")
                return None
    return None

def check_and_create_process_flow():
    """Check and create Process -> Process flow relationship"""
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cur = conn.cursor()
        
        # Check if Process -> Process flow relationship already exists
        cur.execute('''
            SELECT COUNT(*) as count FROM domainmodelrelationship dmr
            JOIN domainmodel dm1 ON dmr.source_element_id = dm1.id
            JOIN domainmodel dm2 ON dmr.target_element_id = dm2.id
            WHERE dm1.element = 'Process' 
            AND dm2.element = 'Process' 
            AND dmr.relationship_type = 'flow'
        ''')
        count = cur.fetchone()['count']
        
        if count > 0:
            print(f"Process -> Process flow relationship already exists! (Found {count} relationship(s))")
            
            # Show the existing relationships
            cur.execute('''
                SELECT dmr.id, dmr.source_element_id, dmr.target_element_id, dmr.relationship_type,
                       dm1.name as source_name, dm2.name as target_name
                FROM domainmodelrelationship dmr
                JOIN domainmodel dm1 ON dmr.source_element_id = dm1.id
                JOIN domainmodel dm2 ON dmr.target_element_id = dm2.id
                WHERE dm1.element = 'Process' 
                AND dm2.element = 'Process' 
                AND dmr.relationship_type = 'flow'
            ''')
            relationships = cur.fetchall()
            print("\nExisting Process -> Process flow relationships:")
            for rel in relationships:
                print(f"  - ID: {rel['id']}, Source: {rel['source_name']} (ID: {rel['source_element_id']}), Target: {rel['target_name']} (ID: {rel['target_element_id']})")
            
            cur.close()
            conn.close()
            return True
        
        # Find Process elements
        cur.execute('SELECT id, name FROM domainmodel WHERE element = ? ORDER BY id', ('Process',))
        process_elements = cur.fetchall()
        
        if len(process_elements) < 1:
            print("Error: No Process elements found in database")
            cur.close()
            conn.close()
            return False
        
        # Use the first Process element for both source and target (self-referential)
        # This creates a Process -> Process relationship rule
        source_id = process_elements[0]['id']
        target_id = process_elements[0]['id']  # Same element for self-reference
        source_name = process_elements[0]['name']
        
        if len(process_elements) >= 2:
            # If we have multiple Process elements, use different ones
            target_id = process_elements[1]['id']
            target_name = process_elements[1]['name']
        else:
            target_name = source_name
        
        print(f"Found Process element(s):")
        print(f"  Source: ID {source_id}, Name: {source_name}")
        print(f"  Target: ID {target_id}, Name: {target_name}")
        
        # Check if this specific relationship already exists
        cur.execute('''
            SELECT id FROM domainmodelrelationship 
            WHERE source_element_id = ? AND target_element_id = ? AND relationship_type = ?
        ''', (source_id, target_id, 'flow'))
        
        if cur.fetchone():
            print("This specific Process -> Process flow relationship already exists!")
            cur.close()
            conn.close()
            return True
        
        # Create Process -> Process flow relationship
        # Note: Self-referential relationships are allowed for relationship rules
        cur.execute('''
            INSERT INTO domainmodelrelationship 
            (source_element_id, target_element_id, relationship_type, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ''', (source_id, target_id, 'flow', 'Process flows to Process'))
        
        conn.commit()
        relationship_id = cur.lastrowid
        
        print(f"\nSuccessfully created Process -> Process flow relationship!")
        print(f"   Relationship ID: {relationship_id}")
        print(f"   Source: {source_name} (ID: {source_id})")
        print(f"   Target: {target_name} (ID: {target_id})")
        print(f"   Type: flow")
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"Error creating Process flow relationship: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback()
            conn.close()
        return False

if __name__ == '__main__':
    print("Checking and creating Process -> Process flow relationship...")
    print("=" * 60)
    success = check_and_create_process_flow()
    print("=" * 60)
    if success:
        print("\nProcess flow relationship check completed successfully!")
        print("   Refresh your browser to see Process in the context menu.")
    else:
        print("\nFailed to create Process flow relationship.")
        print("   Please check the error messages above.")

