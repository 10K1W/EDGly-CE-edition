#!/usr/bin/env python3
"""Check and fix domainelementproperties schema to allow NULL element_id"""

import sqlite3

DB_PATH = 'domainmodel.db'

def check_and_fix_schema():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    try:
        # Check current schema
        cur.execute('PRAGMA table_info(domainelementproperties)')
        columns = cur.fetchall()
        
        print("Current schema:")
        for col in columns:
            notnull = "NOT NULL" if col[3] else "NULLABLE"
            print(f"  {col[1]}: {notnull}")
        
        # Find element_id column
        element_id_col = next((col for col in columns if col[1] == 'element_id'), None)
        
        if element_id_col and element_id_col[3] == 1:  # notnull = 1 means NOT NULL
            print("\n[MIGRATION NEEDED] element_id is NOT NULL, migrating...")
            
            # Create new table
            cur.execute('''
                CREATE TABLE domainelementproperties_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    element_id INTEGER,
                    ragtype TEXT,
                    propertyname TEXT,
                    description TEXT,
                    image_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (element_id) REFERENCES domainmodel(id)
                )
            ''')
            
            # Copy data
            cur.execute('''
                INSERT INTO domainelementproperties_new 
                (id, element_id, ragtype, propertyname, description, image_url, created_at, updated_at)
                SELECT id, element_id, ragtype, propertyname, description, image_url, created_at, updated_at
                FROM domainelementproperties
            ''')
            
            # Drop old and rename
            cur.execute('DROP TABLE domainelementproperties')
            cur.execute('ALTER TABLE domainelementproperties_new RENAME TO domainelementproperties')
            
            # Recreate index
            cur.execute('CREATE INDEX IF NOT EXISTS idx_properties_element ON domainelementproperties(element_id)')
            
            conn.commit()
            print("✓ Migration completed successfully!")
            
            # Verify
            cur.execute('PRAGMA table_info(domainelementproperties)')
            columns = cur.fetchall()
            print("\nNew schema:")
            for col in columns:
                notnull = "NOT NULL" if col[3] else "NULLABLE"
                print(f"  {col[1]}: {notnull}")
        else:
            print("\n✓ Schema is already correct (element_id allows NULL)")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    check_and_fix_schema()

