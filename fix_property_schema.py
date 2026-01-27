#!/usr/bin/env python3
"""Fix domainelementproperties schema to allow NULL element_id"""

import sqlite3

DB_PATH = 'domainmodel.db'

def fix_schema():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    try:
        # Clean up any leftover migration tables
        cur.execute("DROP TABLE IF EXISTS domainelementproperties_new")
        conn.commit()
        
        # Check current schema
        cur.execute('PRAGMA table_info(domainelementproperties)')
        columns = cur.fetchall()
        
        element_id_col = next((col for col in columns if col[1] == 'element_id'), None)
        
        if element_id_col and element_id_col[3] == 1:  # notnull = 1 means NOT NULL
            print("Migrating domainelementproperties table to allow NULL element_id...")
            
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
            print("SUCCESS: Migration completed successfully!")
        else:
            print("SUCCESS: Schema already allows NULL for element_id")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    fix_schema()

