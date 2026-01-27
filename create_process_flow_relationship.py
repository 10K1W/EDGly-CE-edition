#!/usr/bin/env python3
"""
Script to create Process -> Process flow relationship in domainmodelrelationship table
"""

import sqlite3
import os

def get_db_connection():
    """Get database connection"""
    db_path = os.path.join(os.path.dirname(__file__), 'domainmodel.db')
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at {db_path}")
        return None
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None

def create_process_flow_relationship():
    """Create Process -> Process flow relationship"""
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cur = conn.cursor()
        
        # Check if Process -> Process flow relationship already exists
        cur.execute('''
            SELECT COUNT(*) FROM domainmodelrelationship dmr
            JOIN domainmodel dm1 ON dmr.source_element_id = dm1.id
            JOIN domainmodel dm2 ON dmr.target_element_id = dm2.id
            WHERE dm1.element = 'Process' 
            AND dm2.element = 'Process' 
            AND dmr.relationship_type = 'flow'
        ''')
        count = cur.fetchone()[0]
        
        if count > 0:
            print("Process -> Process flow relationship already exists!")
            cur.close()
            conn.close()
            return True
        
        # Find Process elements
        cur.execute('SELECT id, name FROM domainmodel WHERE element = ? ORDER BY id', ('Process',))
        process_elements = cur.fetchall()
        
        if len(process_elements) < 1:
            print(f"Error: No Process elements found in database")
            cur.close()
            conn.close()
            return False
        
        # Use the first Process element for both source and target (self-referential)
        # This creates a Process -> Process relationship rule
        source_id = process_elements[0]['id']
        target_id = process_elements[0]['id']  # Same element for self-reference
        source_name = process_elements[0]['name']
        target_name = process_elements[0]['name']
        
        if len(process_elements) >= 2:
            # If we have multiple Process elements, use different ones
            target_id = process_elements[1]['id']
            target_name = process_elements[1]['name']
        
        print(f"Found Process elements:")
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
        
        # Note: Self-referential relationships (source_id == target_id) are allowed
        # This creates a rule that Process can flow to Process
        
        # Create Process -> Process flow relationship
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
    print("Creating Process -> Process flow relationship...")
    print("=" * 60)
    success = create_process_flow_relationship()
    print("=" * 60)
    if success:
        print("\nProcess flow relationship created successfully!")
        print("   Refresh your browser to see Process in the context menu.")
    else:
        print("\nFailed to create Process flow relationship.")
        print("   Please check the error messages above.")

