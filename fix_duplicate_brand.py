#!/usr/bin/env python3
"""
Script to fix duplicate Brand elements by handling foreign key constraints
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

def find_duplicate_brands():
    """Find duplicate Brand elements"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Find all Brand elements
    cur.execute('''
        SELECT id, name, enterprise, facet, element, created_at
        FROM domainmodel
        WHERE element = "Brand"
        ORDER BY id
    ''')
    
    brands = cur.fetchall()
    print(f"Found {len(brands)} Brand element(s):")
    for brand in brands:
        print(f"  ID: {brand['id']}, Name: {brand['name']}, Enterprise: {brand['enterprise']}, Created: {brand['created_at']}")
    
    if len(brands) < 2:
        print("No duplicates found!")
        conn.close()
        return None, None
    
    # Return the two Brand elements (keep the older one, delete the newer one)
    brand1 = brands[0]
    brand2 = brands[1]
    
    print(f"\nKeeping Brand ID {brand1['id']} (older)")
    print(f"Deleting Brand ID {brand2['id']} (newer)")
    
    conn.close()
    return brand1, brand2

def check_foreign_key_references(element_id):
    """Check what foreign key references exist for an element"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    references = {
        'relationships_as_source': [],
        'relationships_as_target': [],
        'properties': [],
        'diagram_elements': []
    }
    
    # Check relationships where this element is source
    cur.execute('''
        SELECT id, source_element_id, target_element_id, relationship_type
        FROM domainmodelrelationship
        WHERE source_element_id = ?
    ''', (element_id,))
    references['relationships_as_source'] = cur.fetchall()
    
    # Check relationships where this element is target
    cur.execute('''
        SELECT id, source_element_id, target_element_id, relationship_type
        FROM domainmodelrelationship
        WHERE target_element_id = ?
    ''', (element_id,))
    references['relationships_as_target'] = cur.fetchall()
    
    # Check properties
    cur.execute('''
        SELECT id, element_id, propertyname
        FROM domainelementproperties
        WHERE element_id = ?
    ''', (element_id,))
    references['properties'] = cur.fetchall()
    
    # Check diagram elements
    cur.execute('''
        SELECT id, diagram_id, element_id
        FROM plantumldiagram_elements
        WHERE element_id = ?
    ''', (element_id,))
    references['diagram_elements'] = cur.fetchall()
    
    conn.close()
    return references

def reassign_references(from_id, to_id):
    """Reassign all foreign key references from one element to another"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Temporarily disable foreign keys for reassignment
        conn.execute('PRAGMA foreign_keys = OFF')
        
        # Reassign relationships where element is source
        cur.execute('''
            UPDATE domainmodelrelationship
            SET source_element_id = ?
            WHERE source_element_id = ?
        ''', (to_id, from_id))
        source_count = cur.rowcount
        
        # Reassign relationships where element is target
        cur.execute('''
            UPDATE domainmodelrelationship
            SET target_element_id = ?
            WHERE target_element_id = ?
        ''', (to_id, from_id))
        target_count = cur.rowcount
        
        # Reassign properties
        cur.execute('''
            UPDATE domainelementproperties
            SET element_id = ?
            WHERE element_id = ?
        ''', (to_id, from_id))
        prop_count = cur.rowcount
        
        # For diagram elements, check if reassignment would cause UNIQUE constraint violation
        # If so, delete the duplicate reference instead
        cur.execute('''
            SELECT diagram_id FROM plantumldiagram_elements
            WHERE element_id = ?
        ''', (from_id,))
        diagram_refs_to_move = cur.fetchall()
        
        diagram_count = 0
        diagram_deleted = 0
        
        for ref in diagram_refs_to_move:
            diagram_id = ref[0]  # Access by index since it's a Row object
            # Check if the target element already has a reference to this diagram
            cur.execute('''
                SELECT id FROM plantumldiagram_elements
                WHERE diagram_id = ? AND element_id = ?
            ''', (diagram_id, to_id))
            existing = cur.fetchone()
            
            if existing:
                # Duplicate reference exists, delete the one we're moving
                cur.execute('''
                    DELETE FROM plantumldiagram_elements
                    WHERE diagram_id = ? AND element_id = ?
                ''', (diagram_id, from_id))
                diagram_deleted += 1
            else:
                # No duplicate, reassign it
                cur.execute('''
                    UPDATE plantumldiagram_elements
                    SET element_id = ?
                    WHERE diagram_id = ? AND element_id = ?
                ''', (to_id, diagram_id, from_id))
                diagram_count += 1
        
        conn.commit()
        conn.execute('PRAGMA foreign_keys = ON')
        
        print(f"\nReassigned references:")
        print(f"  Relationships as source: {source_count}")
        print(f"  Relationships as target: {target_count}")
        print(f"  Properties: {prop_count}")
        print(f"  Diagram elements reassigned: {diagram_count}")
        print(f"  Duplicate diagram elements deleted: {diagram_deleted}")
        
        conn.close()
        return True
    except Exception as e:
        conn.rollback()
        conn.execute('PRAGMA foreign_keys = ON')
        conn.close()
        print(f"Error reassigning references: {e}")
        import traceback
        traceback.print_exc()
        return False

def delete_element(element_id):
    """Delete an element after reassigning references"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        conn.execute('PRAGMA foreign_keys = ON')
        
        cur.execute('DELETE FROM domainmodel WHERE id = ?', (element_id,))
        
        if cur.rowcount > 0:
            conn.commit()
            print(f"\nSuccessfully deleted Brand element ID {element_id}")
            conn.close()
            return True
        else:
            print(f"\nNo element found with ID {element_id}")
            conn.close()
            return False
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"Error deleting element: {e}")
        return False

def main():
    print("=" * 60)
    print("Duplicate Brand Element Cleanup Script")
    print("=" * 60)
    
    # Find duplicates
    brand1, brand2 = find_duplicate_brands()
    
    if not brand1 or not brand2:
        return
    
    # Check references for the element to be deleted
    print(f"\nChecking foreign key references for Brand ID {brand2['id']}...")
    references = check_foreign_key_references(brand2['id'])
    
    total_refs = (len(references['relationships_as_source']) + 
                  len(references['relationships_as_target']) + 
                  len(references['properties']) + 
                  len(references['diagram_elements']))
    
    if total_refs > 0:
        print(f"\nFound {total_refs} foreign key reference(s):")
        print(f"  Relationships as source: {len(references['relationships_as_source'])}")
        print(f"  Relationships as target: {len(references['relationships_as_target'])}")
        print(f"  Properties: {len(references['properties'])}")
        print(f"  Diagram elements: {len(references['diagram_elements'])}")
        
        # Reassign references to the element we're keeping
        print(f"\nReassigning references from Brand ID {brand2['id']} to Brand ID {brand1['id']}...")
        if not reassign_references(brand2['id'], brand1['id']):
            print("Failed to reassign references. Aborting.")
            return
    else:
        print("\nNo foreign key references found. Safe to delete.")
    
    # Delete the duplicate
    print(f"\nDeleting duplicate Brand element ID {brand2['id']}...")
    if delete_element(brand2['id']):
        print("\n" + "=" * 60)
        print("SUCCESS: Duplicate Brand element has been deleted!")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("ERROR: Failed to delete duplicate Brand element")
        print("=" * 60)

if __name__ == '__main__':
    main()

