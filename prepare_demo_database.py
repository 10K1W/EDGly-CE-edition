#!/usr/bin/env python3
"""
Script to prepare database for beta v0.1 release
Filters database to only include Demo Enterprise elements
Creates a clean database file for distribution
"""
import sqlite3
import os
import shutil
from pathlib import Path

def prepare_demo_database(source_db='domainmodel.db', output_db='domainmodel_demo.db'):
    """Create a database with only Demo Enterprise elements"""
    
    print(f"Preparing Demo Enterprise database from {source_db}...")
    
    # Check if source database exists
    if not os.path.exists(source_db):
        print(f"ERROR: Source database {source_db} not found!")
        return False
    
    # Backup original if output exists
    if os.path.exists(output_db):
        backup = output_db + '.bak'
        if os.path.exists(backup):
            os.remove(backup)
        shutil.copy2(output_db, backup)
        print(f"Backed up existing {output_db} to {backup}")
    
    # Create new database
    print(f"Creating filtered database: {output_db}")
    conn = sqlite3.connect(output_db)
    cur = conn.cursor()
    
    # Get connection to source database
    source_conn = sqlite3.connect(source_db)
    source_cur = source_conn.cursor()
    
    try:
        # Copy schema from source database
        # Read all CREATE TABLE statements from source
        source_cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = source_cur.fetchall()
        
        for (sql,) in tables:
            if sql:
                cur.execute(sql)
        
        # Copy indexes
        source_cur.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")
        indexes = source_cur.fetchall()
        
        for (sql,) in indexes:
            if sql:
                try:
                    cur.execute(sql)
                except:
                    pass  # Some indexes may fail if table is empty
        
        conn.commit()
        
        # Get all Demo enterprise element IDs (case-insensitive)
        source_cur.execute('''
            SELECT id FROM domainmodel 
            WHERE LOWER(enterprise) = 'demo' OR enterprise = 'Demo'
        ''')
        demo_element_ids = [row[0] for row in source_cur.fetchall()]
        
        if not demo_element_ids:
            print("WARNING: No Demo enterprise elements found!")
            # Check what enterprises exist
            source_cur.execute('SELECT DISTINCT enterprise FROM domainmodel WHERE enterprise IS NOT NULL')
            enterprises = [row[0] for row in source_cur.fetchall()]
            print(f"Available enterprises: {enterprises}")
            source_conn.close()
            conn.close()
            os.remove(output_db)
            return False
        
        print(f"Found {len(demo_element_ids)} Demo enterprise elements")
        
        # Copy Demo enterprise elements
        placeholders = ','.join(['?'] * len(demo_element_ids))
        source_cur.execute(f'SELECT * FROM domainmodel WHERE id IN ({placeholders})', demo_element_ids)
        elements = source_cur.fetchall()
        
        # Get column names
        source_cur.execute('PRAGMA table_info(domainmodel)')
        columns = [col[1] for col in source_cur.fetchall()]
        col_names = ', '.join(columns)
        placeholders_insert = ', '.join(['?'] * len(columns))
        
        for element in elements:
            cur.execute(f'INSERT INTO domainmodel ({col_names}) VALUES ({placeholders_insert})', element)
        
        print(f"Copied {len(elements)} elements")
        
        # Copy relationships where both source and target are Demo enterprise
        source_cur.execute(f'''
            SELECT r.* FROM domainmodelrelationship r
            WHERE r.source_element_id IN ({placeholders})
              AND r.target_element_id IN ({placeholders})
        ''', demo_element_ids + demo_element_ids)
        relationships = source_cur.fetchall()
        
        if relationships:
            source_cur.execute('PRAGMA table_info(domainmodelrelationship)')
            rel_columns = [col[1] for col in source_cur.fetchall()]
            rel_col_names = ', '.join(rel_columns)
            rel_placeholders = ', '.join(['?'] * len(rel_columns))
            
            for rel in relationships:
                cur.execute(f'INSERT INTO domainmodelrelationship ({rel_col_names}) VALUES ({rel_placeholders})', rel)
        
        print(f"Copied {len(relationships)} relationships")
        
        # Copy properties for Demo enterprise elements
        source_cur.execute(f'''
            SELECT p.* FROM domainelementproperties p
            WHERE p.element_id IN ({placeholders})
        ''', demo_element_ids)
        properties = source_cur.fetchall()
        
        if properties:
            source_cur.execute('PRAGMA table_info(domainelementproperties)')
            prop_columns = [col[1] for col in source_cur.fetchall()]
            prop_col_names = ', '.join(prop_columns)
            prop_placeholders = ', '.join(['?'] * len(prop_columns))
            
            for prop in properties:
                cur.execute(f'INSERT INTO domainelementproperties ({prop_col_names}) VALUES ({prop_placeholders})', prop)
        
        print(f"Copied {len(properties)} properties")
        
        # Copy canvas tables if they exist (they should be empty for a fresh install)
        canvas_tables = [
            'canvas_models', 'canvas_element_instances', 'canvas_relationships',
            'canvas_property_instances', 'canvas_template_segments', 'canvas_template_segment_associations'
        ]
        
        for table_name in canvas_tables:
            try:
                source_cur.execute(f'SELECT sql FROM sqlite_master WHERE type="table" AND name=?', (table_name,))
                result = source_cur.fetchone()
                if result and result[0]:
                    cur.execute(result[0])
                    conn.commit()
            except:
                pass
        
        # Copy other tables that might exist (empty for demo)
        other_tables = [
            'plantumldiagrams', 'plantumldiagram_elements',
            'design_rules', 'design_rule_violations', 'audit_log'
        ]
        
        for table_name in other_tables:
            try:
                source_cur.execute(f'SELECT sql FROM sqlite_master WHERE type="table" AND name=?', (table_name,))
                result = source_cur.fetchone()
                if result and result[0]:
                    cur.execute(result[0])
                    conn.commit()
            except:
                pass
        
        conn.commit()
        
        # Verify the database
        cur.execute('SELECT COUNT(*) FROM domainmodel')
        element_count = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM domainmodelrelationship')
        rel_count = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM domainelementproperties')
        prop_count = cur.fetchone()[0]
        
        print(f"\nDatabase prepared successfully!")
        print(f"  Elements: {element_count}")
        print(f"  Relationships: {rel_count}")
        print(f"  Properties: {prop_count}")
        
        source_conn.close()
        conn.close()
        
        return True
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        source_conn.close()
        conn.close()
        if os.path.exists(output_db):
            os.remove(output_db)
        return False

if __name__ == '__main__':
    success = prepare_demo_database()
    if success:
        print("\n✅ Demo database prepared: domainmodel_demo.db")
    else:
        print("\n❌ Failed to prepare demo database")
        exit(1)
