#!/usr/bin/env python3
"""
Script to create relationship records based on relationship types in the UI
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

def get_all_elements():
    """Get all elements from domainmodel"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT id, name, enterprise, facet, element FROM domainmodel ORDER BY id')
    elements = cur.fetchall()
    conn.close()
    return elements

def get_existing_relationships():
    """Get all existing relationships to avoid duplicates"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT source_element_id, target_element_id, relationship_type 
        FROM domainmodelrelationship
    ''')
    relationships = cur.fetchall()
    conn.close()
    return {(r[0], r[1], r[2]) for r in relationships}

def create_relationship(source_id, target_id, relationship_type, description=None):
    """Create a relationship record"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Check if relationship already exists
        cur.execute('''
            SELECT id FROM domainmodelrelationship 
            WHERE source_element_id = ? AND target_element_id = ? AND relationship_type = ?
        ''', (source_id, target_id, relationship_type))
        
        if cur.fetchone():
            return False  # Relationship already exists
        
        # Create the relationship
        cur.execute('''
            INSERT INTO domainmodelrelationship 
            (source_element_id, target_element_id, relationship_type, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ''', (source_id, target_id, relationship_type, description))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"Error creating relationship: {e}")
        return False

def create_relationships_from_types():
    """Create relationships based on relationship types and element matching"""
    
    # Relationship type mappings from the UI
    # Format: relationship_type: (source_element_type, target_element_type)
    relationship_rules = {
        # Base Facet Relationships
        'performs': ('People', 'Activity'),
        'uses': ('People', 'Object'),
        'achieves': ('People', 'Outcome'),
        
        # Architecture Facet Relationships
        'requires': ('Capability', 'Asset'),  # capability_requires_asset maps to 'requires'
        'requires': ('Process', 'Asset'),     # process_requires_asset maps to 'requires'
        'realises': ('Process', 'Capability'),
        
        # Identity Facet Relationships
        'pursue': ('People', 'Purpose'),
        'pursue': ('Organisation', 'Purpose'),  # organisation_pursues_purpose maps to 'pursue'
        'expresses': ('Content', 'Purpose'),
        'conveys': ('Content', 'Story'),
        'contextualises': ('Story', 'Purpose'),
        
        # Experience Facet Relationships
        'is_part_of': ('Task', 'Journey'),
        'traverses': ('Journey', 'Channel'),
        
        # Product Relationships
        'creates': ('Process', 'Product'),
        'makes': ('Organisation', 'Product'),
        'features in': ('Product', 'Journey'),
        'serves': ('Product', 'Task'),
        'embodies': ('Product', 'Brand'),
        
        # Brand Relationships
        'perceives': ('People', 'Brand'),
        'appears in': ('Brand', 'Journey'),
        
        # Organisation Relationships
        'performs': ('Organisation', 'Process'),  # This is the same as People performs Activity
    }
    
    # More specific mappings for UI relationship types to database types
    ui_to_db_mapping = {
        'capability_requires_asset': ('requires', 'Capability', 'Asset'),
        'process_requires_asset': ('requires', 'Process', 'Asset'),
        'organisation_pursues_purpose': ('pursue', 'Organisation', 'Purpose'),
    }
    
    # Get all elements
    elements = get_all_elements()
    existing_rels = get_existing_relationships()
    
    # Create a lookup by element type
    elements_by_type = {}
    for elem in elements:
        elem_type = (elem['element'] or '').strip()
        if elem_type:
            if elem_type not in elements_by_type:
                elements_by_type[elem_type] = []
            elements_by_type[elem_type].append(elem)
    
    relationships_created = 0
    relationships_skipped = 0
    
    print("=" * 80)
    print("Creating Relationships from Relationship Types")
    print("=" * 80)
    
    # Process UI-specific mappings first
    for ui_type, (db_type, source_type, target_type) in ui_to_db_mapping.items():
        source_elems = elements_by_type.get(source_type, [])
        target_elems = elements_by_type.get(target_type, [])
        
        print(f"\nProcessing: {ui_type} -> {db_type}")
        print(f"  Source: {source_type} ({len(source_elems)} elements)")
        print(f"  Target: {target_type} ({len(target_elems)} elements)")
        
        for source in source_elems:
            for target in target_elems:
                # Check enterprise matching - both should be in same enterprise or both null
                source_ent = source['enterprise'] or ''
                target_ent = target['enterprise'] or ''
                
                if source_ent and target_ent and source_ent.lower() != target_ent.lower():
                    continue  # Skip if different enterprises
                
                if (source['id'], target['id'], db_type) not in existing_rels:
                    if create_relationship(source['id'], target['id'], db_type):
                        relationships_created += 1
                        print(f"    Created: {source['name']} ({source_type}) -> {target['name']} ({target_type})")
                    else:
                        relationships_skipped += 1
                else:
                    relationships_skipped += 1
    
    # Process standard relationship types
    standard_rules = {
        'performs': [('People', 'Activity'), ('Organisation', 'Process')],
        'uses': [('People', 'Object')],
        'achieves': [('People', 'Outcome')],
        'realises': [('Process', 'Capability')],
        'pursue': [('People', 'Purpose'), ('Organisation', 'Purpose')],
        'expresses': [('Content', 'Purpose')],
        'conveys': [('Content', 'Story')],
        'contextualises': [('Story', 'Purpose')],
        'is_part_of': [('Task', 'Journey')],
        'traverses': [('Journey', 'Channel')],
        'creates': [('Process', 'Product')],
        'makes': [('Organisation', 'Product')],
        'features in': [('Product', 'Journey')],
        'serves': [('Product', 'Task')],
        'embodies': [('Product', 'Brand')],
        'perceives': [('People', 'Brand')],
        'appears in': [('Brand', 'Journey')],
    }
    
    for rel_type, type_pairs in standard_rules.items():
        for source_type, target_type in type_pairs:
            source_elems = elements_by_type.get(source_type, [])
            target_elems = elements_by_type.get(target_type, [])
            
            if not source_elems or not target_elems:
                continue
            
            print(f"\nProcessing: {rel_type}")
            print(f"  Source: {source_type} ({len(source_elems)} elements)")
            print(f"  Target: {target_type} ({len(target_elems)} elements)")
            
            for source in source_elems:
                for target in target_elems:
                    # Check enterprise matching
                    source_ent = source['enterprise'] or ''
                    target_ent = target['enterprise'] or ''
                    
                    if source_ent and target_ent and source_ent.lower() != target_ent.lower():
                        continue
                    
                    if (source['id'], target['id'], rel_type) not in existing_rels:
                        if create_relationship(source['id'], target['id'], rel_type):
                            relationships_created += 1
                            print(f"    Created: {source['name']} ({source_type}) -> {target['name']} ({target_type})")
                        else:
                            relationships_skipped += 1
                    else:
                        relationships_skipped += 1
    
    print("\n" + "=" * 80)
    print(f"SUMMARY:")
    print(f"  Relationships created: {relationships_created}")
    print(f"  Relationships skipped (already exist): {relationships_skipped}")
    print("=" * 80)

if __name__ == '__main__':
    create_relationships_from_types()

