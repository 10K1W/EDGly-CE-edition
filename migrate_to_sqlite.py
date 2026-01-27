#!/usr/bin/env python3
"""
Migration script to copy data from Neon PostgreSQL to SQLite
This script reads all data from Neon and inserts it into SQLite
"""

import psycopg2
import sqlite3
import os
from datetime import datetime

# Neon PostgreSQL connection string
NEON_DATABASE_URL = os.getenv('DATABASE_URL', 
    'postgresql://neondb_owner:npg_L5yt4aoVrmYg@ep-wispy-glitter-a9z6awgo-pooler.gwc.azure.neon.tech/neondb?channel_binding=require&sslmode=require')

# SQLite database file path
SQLITE_DB_PATH = os.getenv('DB_PATH', 'domainmodel.db')

def get_neon_connection():
    """Connect to Neon PostgreSQL database"""
    try:
        conn = psycopg2.connect(NEON_DATABASE_URL, sslmode='require')
        return conn
    except Exception as e:
        print(f"Error connecting to Neon database: {e}")
        return None

def init_sqlite_database(sqlite_conn):
    """Initialize SQLite database with all required tables"""
    cur = sqlite_conn.cursor()
    
    try:
        # Create domainmodel table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS domainmodel (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                enterprise TEXT,
                facet TEXT,
                element TEXT,
                image_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create domainmodelrelationship table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS domainmodelrelationship (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_element_id INTEGER NOT NULL,
                target_element_id INTEGER NOT NULL,
                relationship_type TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (source_element_id) REFERENCES domainmodel(id),
                FOREIGN KEY (target_element_id) REFERENCES domainmodel(id)
            )
        ''')
        
        # Create domainelementproperties table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS domainelementproperties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                element_id INTEGER NOT NULL,
                ragtype TEXT,
                propertyname TEXT,
                description TEXT,
                image_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (element_id) REFERENCES domainmodel(id)
            )
        ''')
        
        # Create plantumldiagrams table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS plantumldiagrams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                plantuml_code TEXT,
                encoded_url TEXT,
                enterprise_filter TEXT,
                elements_count INTEGER,
                relationships_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create plantumldiagram_elements table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS plantumldiagram_elements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                diagram_id INTEGER NOT NULL,
                element_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (diagram_id) REFERENCES plantumldiagrams(id),
                FOREIGN KEY (element_id) REFERENCES domainmodel(id),
                UNIQUE(diagram_id, element_id)
            )
        ''')
        
        # Create indexes
        cur.execute('CREATE INDEX IF NOT EXISTS idx_domainmodel_enterprise ON domainmodel(enterprise)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_domainmodel_facet ON domainmodel(facet)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_relationship_source ON domainmodelrelationship(source_element_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_relationship_target ON domainmodelrelationship(target_element_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_properties_element ON domainelementproperties(element_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_diagram_elements_diagram ON plantumldiagram_elements(diagram_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_diagram_elements_element ON plantumldiagram_elements(element_id)')
        
        sqlite_conn.commit()
        print("[Init] SQLite database tables initialized")
        return True
    except Exception as e:
        print(f"[Init] Error initializing SQLite database: {e}")
        sqlite_conn.rollback()
        return False
    finally:
        cur.close()

def get_sqlite_connection():
    """Connect to SQLite database"""
    try:
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        return conn
    except Exception as e:
        print(f"Error connecting to SQLite database: {e}")
        return None

def migrate_table(neon_conn, sqlite_conn, table_name, columns, order_by=None):
    """Migrate a single table from Neon to SQLite"""
    print(f"\n[Migrate] Migrating table: {table_name}")
    
    neon_cur = neon_conn.cursor()
    sqlite_cur = sqlite_conn.cursor()
    
    try:
        # Build SELECT query
        select_query = f'SELECT {", ".join(columns)} FROM "{table_name}"'
        if order_by:
            select_query += f' ORDER BY {order_by}'
        
        # Fetch data from Neon
        neon_cur.execute(select_query)
        rows = neon_cur.fetchall()
        
        print(f"[Migrate] Found {len(rows)} rows in Neon {table_name}")
        
        if len(rows) == 0:
            print(f"[Migrate] No data to migrate for {table_name}")
            return 0
        
        # Build INSERT query for SQLite
        placeholders = ', '.join(['?'] * len(columns))
        insert_query = f'INSERT INTO {table_name} ({", ".join(columns)}) VALUES ({placeholders})'
        
        # Insert data into SQLite
        inserted_count = 0
        for row in rows:
            try:
                sqlite_cur.execute(insert_query, row)
                inserted_count += 1
            except sqlite3.IntegrityError as e:
                print(f"[Migrate] Warning: Skipping duplicate row in {table_name}: {e}")
                continue
            except Exception as e:
                print(f"[Migrate] Error inserting row into {table_name}: {e}")
                print(f"[Migrate] Row data: {row}")
                continue
        
        sqlite_conn.commit()
        print(f"[Migrate] Successfully inserted {inserted_count} rows into SQLite {table_name}")
        return inserted_count
        
    except Exception as e:
        print(f"[Migrate] Error migrating {table_name}: {e}")
        sqlite_conn.rollback()
        return 0
    finally:
        neon_cur.close()

def migrate_domainmodel(neon_conn, sqlite_conn):
    """Migrate domainmodel table"""
    columns = ['id', 'name', 'description', 'enterprise', 'facet', 'element', 'image_url', 'created_at', 'updated_at']
    return migrate_table(neon_conn, sqlite_conn, 'domainmodel', columns, 'id')

def migrate_domainmodelrelationship(neon_conn, sqlite_conn):
    """Migrate domainmodelrelationship table"""
    columns = ['id', 'source_element_id', 'target_element_id', 'relationship_type', 'description', 'created_at', 'updated_at']
    return migrate_table(neon_conn, sqlite_conn, 'domainmodelrelationship', columns, 'id')

def migrate_domainelementproperties(neon_conn, sqlite_conn):
    """Migrate domainelementproperties table"""
    columns = ['id', 'element_id', 'ragtype', 'propertyname', 'description', 'image_url', 'created_at', 'updated_at']
    return migrate_table(neon_conn, sqlite_conn, 'domainelementproperties', columns, 'id')

def migrate_plantumldiagrams(neon_conn, sqlite_conn):
    """Migrate plantumldiagrams table"""
    columns = ['id', 'title', 'plantuml_code', 'encoded_url', 'enterprise_filter', 'elements_count', 'relationships_count', 'created_at', 'updated_at']
    return migrate_table(neon_conn, sqlite_conn, 'plantumldiagrams', columns, 'id')

def migrate_plantumldiagram_elements(neon_conn, sqlite_conn):
    """Migrate plantumldiagram_elements table"""
    columns = ['id', 'diagram_id', 'element_id', 'created_at']
    return migrate_table(neon_conn, sqlite_conn, 'plantumldiagram_elements', columns, 'id')

def reset_sqlite_sequences(sqlite_conn):
    """Reset SQLite sequences to continue from highest ID"""
    sqlite_cur = sqlite_conn.cursor()
    
    try:
        # Get max IDs from each table
        tables = ['domainmodel', 'domainmodelrelationship', 'domainelementproperties', 'plantumldiagrams', 'plantumldiagram_elements']
        
        for table in tables:
            sqlite_cur.execute(f'SELECT MAX(id) FROM {table}')
            max_id = sqlite_cur.fetchone()[0]
            if max_id:
                # SQLite uses sqlite_sequence table for AUTOINCREMENT
                sqlite_cur.execute(f'UPDATE sqlite_sequence SET seq = ? WHERE name = ?', (max_id, table))
                print(f"[Migrate] Set sequence for {table} to {max_id}")
        
        sqlite_conn.commit()
    except Exception as e:
        print(f"[Migrate] Warning: Could not reset sequences: {e}")
        # sqlite_sequence might not exist if no AUTOINCREMENT tables have been used yet
    finally:
        sqlite_cur.close()

def main():
    """Main migration function"""
    print("=" * 60)
    print("Neon PostgreSQL to SQLite Migration Script")
    print("=" * 60)
    print(f"Source: Neon PostgreSQL")
    print(f"Destination: SQLite ({SQLITE_DB_PATH})")
    print(f"Started: {datetime.now()}")
    print("=" * 60)
    
    # Connect to databases
    print("\n[Connect] Connecting to Neon PostgreSQL...")
    neon_conn = get_neon_connection()
    if not neon_conn:
        print("[Error] Failed to connect to Neon database. Exiting.")
        return
    
    print("[Connect] Connected to Neon PostgreSQL")
    
    print("\n[Connect] Connecting to SQLite...")
    sqlite_conn = get_sqlite_connection()
    if not sqlite_conn:
        print("[Error] Failed to connect to SQLite database. Exiting.")
        neon_conn.close()
        return
    
    print(f"[Connect] Connected to SQLite ({SQLITE_DB_PATH})")
    
    # Initialize SQLite database tables
    print("\n[Init] Initializing SQLite database tables...")
    if not init_sqlite_database(sqlite_conn):
        print("[Error] Failed to initialize SQLite database. Exiting.")
        neon_conn.close()
        sqlite_conn.close()
        return
    
    # Check if SQLite database is empty
    sqlite_cur = sqlite_conn.cursor()
    sqlite_cur.execute('SELECT COUNT(*) FROM domainmodel')
    existing_count = sqlite_cur.fetchone()[0]
    sqlite_cur.close()
    
    if existing_count > 0:
        response = input(f"\n[Warning] SQLite database already contains {existing_count} records in domainmodel table.\n"
                         "Do you want to continue? This may create duplicates. (yes/no): ")
        if response.lower() != 'yes':
            print("[Migrate] Migration cancelled by user.")
            neon_conn.close()
            sqlite_conn.close()
            return
    
    # Migrate tables in order (respecting foreign key dependencies)
    total_migrated = 0
    
    # Step 1: Migrate base tables (no dependencies)
    print("\n" + "=" * 60)
    print("Step 1: Migrating base tables")
    print("=" * 60)
    
    count = migrate_domainmodel(neon_conn, sqlite_conn)
    total_migrated += count
    
    count = migrate_plantumldiagrams(neon_conn, sqlite_conn)
    total_migrated += count
    
    # Step 2: Migrate dependent tables
    print("\n" + "=" * 60)
    print("Step 2: Migrating dependent tables")
    print("=" * 60)
    
    count = migrate_domainmodelrelationship(neon_conn, sqlite_conn)
    total_migrated += count
    
    count = migrate_domainelementproperties(neon_conn, sqlite_conn)
    total_migrated += count
    
    count = migrate_plantumldiagram_elements(neon_conn, sqlite_conn)
    total_migrated += count
    
    # Reset sequences
    print("\n[Migrate] Resetting SQLite sequences...")
    reset_sqlite_sequences(sqlite_conn)
    
    # Summary
    print("\n" + "=" * 60)
    print("Migration Summary")
    print("=" * 60)
    print(f"Total rows migrated: {total_migrated}")
    print(f"Completed: {datetime.now()}")
    print("=" * 60)
    
    # Verify migration
    print("\n[Verify] Verifying migration...")
    sqlite_cur = sqlite_conn.cursor()
    
    neon_cur = neon_conn.cursor()
    neon_cur.execute('SELECT COUNT(*) FROM domainmodel')
    neon_count = neon_cur.fetchone()[0]
    
    sqlite_cur.execute('SELECT COUNT(*) FROM domainmodel')
    sqlite_count = sqlite_cur.fetchone()[0]
    
    print(f"[Verify] domainmodel: Neon={neon_count}, SQLite={sqlite_count}")
    
    neon_cur.execute('SELECT COUNT(*) FROM domainmodelrelationship')
    neon_count = neon_cur.fetchone()[0]
    sqlite_cur.execute('SELECT COUNT(*) FROM domainmodelrelationship')
    sqlite_count = sqlite_cur.fetchone()[0]
    print(f"[Verify] domainmodelrelationship: Neon={neon_count}, SQLite={sqlite_count}")
    
    neon_cur.execute('SELECT COUNT(*) FROM domainelementproperties')
    neon_count = neon_cur.fetchone()[0]
    sqlite_cur.execute('SELECT COUNT(*) FROM domainelementproperties')
    sqlite_count = sqlite_cur.fetchone()[0]
    print(f"[Verify] domainelementproperties: Neon={neon_count}, SQLite={sqlite_count}")
    
    neon_cur.execute('SELECT COUNT(*) FROM plantumldiagrams')
    neon_count = neon_cur.fetchone()[0]
    sqlite_cur.execute('SELECT COUNT(*) FROM plantumldiagrams')
    sqlite_count = sqlite_cur.fetchone()[0]
    print(f"[Verify] plantumldiagrams: Neon={neon_count}, SQLite={sqlite_count}")
    
    neon_cur.execute('SELECT COUNT(*) FROM plantumldiagram_elements')
    neon_count = neon_cur.fetchone()[0]
    sqlite_cur.execute('SELECT COUNT(*) FROM plantumldiagram_elements')
    sqlite_count = sqlite_cur.fetchone()[0]
    print(f"[Verify] plantumldiagram_elements: Neon={neon_count}, SQLite={sqlite_count}")
    
    neon_cur.close()
    sqlite_cur.close()
    
    # Close connections
    neon_conn.close()
    sqlite_conn.close()
    
    print("\n[Migrate] Migration completed successfully!")
    print(f"[Migrate] SQLite database is ready at: {SQLITE_DB_PATH}")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n[Migrate] Migration interrupted by user.")
    except Exception as e:
        print(f"\n[Migrate] Fatal error: {e}")
        import traceback
        traceback.print_exc()

