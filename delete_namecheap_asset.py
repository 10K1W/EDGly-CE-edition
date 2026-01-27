#!/usr/bin/env python3
"""
Script to delete Namecheap Asset element from the database
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

def find_namecheap_asset():
    """Find the Namecheap Asset element"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Find the Namecheap Asset element
    cur.execute('''
        SELECT id, name, enterprise, facet, element, created_at
        FROM domainmodel
        WHERE name LIKE '%Namecheap%' AND element = 'Asset'
    ''')
    
    records = cur.fetchall()
    
    if not records:
        print("No Namecheap Asset element found!")
        conn.close()
        return None
    
    print(f"Found {len(records)} Namecheap Asset element(s):")
    for record in records:
        print(f"  ID: {record['id']}, Name: {record['name']}, Enterprise: {record['enterprise']}, Created: {record['created_at']}")
    
    conn.close()
    return records[0] if records else None

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

def delete_element_with_references(element_id):
    """Delete an element and all its foreign key references"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Temporarily disable foreign keys
        conn.execute('PRAGMA foreign_keys = OFF')
        
        # Delete all related records
        relationships_deleted_as_source = 0
        relationships_deleted_as_target = 0
        properties_deleted = 0
        diagram_elements_deleted = 0
        history_deleted = 0
        
        # Delete relationships where element is source
        try:
            cur.execute('DELETE FROM domainmodelrelationship WHERE source_element_id = ?', (element_id,))
            relationships_deleted_as_source = cur.rowcount
        except Exception as e:
            print(f"Warning: Could not delete relationships as source: {e}")
        
        # Delete relationships where element is target
        try:
            cur.execute('DELETE FROM domainmodelrelationship WHERE target_element_id = ?', (element_id,))
            relationships_deleted_as_target = cur.rowcount
        except Exception as e:
            print(f"Warning: Could not delete relationships as target: {e}")
        
        # Delete properties
        try:
            cur.execute('DELETE FROM domainelementproperties WHERE element_id = ?', (element_id,))
            properties_deleted = cur.rowcount
        except Exception as e:
            print(f"Warning: Could not delete properties: {e}")
        
        # Delete diagram elements
        try:
            cur.execute('DELETE FROM plantumldiagram_elements WHERE element_id = ?', (element_id,))
            diagram_elements_deleted = cur.rowcount
        except Exception as e:
            print(f"Warning: Could not delete diagram elements: {e}")
        
        # Delete element versions
        try:
            cur.execute('DELETE FROM element_versions WHERE element_id = ?', (element_id,))
            history_deleted = cur.rowcount
        except Exception as e:
            print(f"Warning: Could not delete element versions: {e}")
        
        # Delete the element itself
        cur.execute('DELETE FROM domainmodel WHERE id = ?', (element_id,))
        element_deleted = cur.rowcount
        
        # Re-enable foreign keys
        conn.execute('PRAGMA foreign_keys = ON')
        
        if element_deleted > 0:
            conn.commit()
            print(f"\nSuccessfully deleted Namecheap Asset element ID {element_id}")
            print(f"Deleted references:")
            print(f"  Relationships as source: {relationships_deleted_as_source}")
            print(f"  Relationships as target: {relationships_deleted_as_target}")
            print(f"  Properties: {properties_deleted}")
            print(f"  Diagram elements: {diagram_elements_deleted}")
            print(f"  History records: {history_deleted}")
            conn.close()
            return True
        else:
            print(f"\nNo element found with ID {element_id}")
            conn.close()
            return False
    except Exception as e:
        conn.rollback()
        conn.execute('PRAGMA foreign_keys = ON')
        conn.close()
        print(f"Error deleting element: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("=" * 60)
    print("Delete Namecheap Asset Element")
    print("=" * 60)
    
    # Find the element
    element = find_namecheap_asset()
    
    if not element:
        return
    
    element_id = element['id']
    element_name = element['name']
    
    # Check references
    print(f"\nChecking foreign key references for '{element_name}' (ID: {element_id})...")
    references = check_foreign_key_references(element_id)
    
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
    
    # Confirm deletion
    print(f"\nAre you sure you want to delete '{element_name}' (ID: {element_id})?")
    confirm = input("Type 'yes' to confirm: ")
    
    if confirm.lower() != 'yes':
        print("Deletion cancelled.")
        return
    
    # Delete the element
    print(f"\nDeleting '{element_name}' (ID: {element_id})...")
    if delete_element_with_references(element_id):
        print("\n" + "=" * 60)
        print("SUCCESS: Namecheap Asset element has been deleted!")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("ERROR: Failed to delete Namecheap Asset element")
        print("=" * 60)

if __name__ == '__main__':
    main()

