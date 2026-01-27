#!/usr/bin/env python3
"""
Script to identify and remove duplicate records from domainelementproperties table.
Duplicates are identified by: propertyname, ragtype, description, image_url (and optionally element_id)
"""

import sqlite3
import sys

DB_PATH = 'domainmodel.db'

def get_db_connection():
    """Create and return a SQLite database connection"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

def find_duplicates(include_element_id=False):
    """Find duplicate properties"""
    conn = get_db_connection()
    if not conn:
        return []
    
    try:
        cur = conn.cursor()
        
        if include_element_id:
            # Find duplicates including element_id
            cur.execute('''
                SELECT propertyname, ragtype, description, image_url, element_id, COUNT(*) as count
                FROM domainelementproperties
                GROUP BY propertyname, ragtype, description, image_url, element_id
                HAVING COUNT(*) > 1
                ORDER BY count DESC, propertyname
            ''')
        else:
            # Find duplicates ignoring element_id (template properties)
            cur.execute('''
                SELECT propertyname, ragtype, description, image_url, COUNT(*) as count
                FROM domainelementproperties
                GROUP BY propertyname, ragtype, description, image_url
                HAVING COUNT(*) > 1
                ORDER BY count DESC, propertyname
            ''')
        
        duplicates = cur.fetchall()
        return duplicates
    except Exception as e:
        print(f"Error finding duplicates: {e}")
        return []
    finally:
        conn.close()

def get_duplicate_records(propertyname, ragtype, description, image_url, element_id=None):
    """Get all records matching the duplicate criteria"""
    conn = get_db_connection()
    if not conn:
        return []
    
    try:
        cur = conn.cursor()
        
        if element_id is not None:
            cur.execute('''
                SELECT id, element_id, propertyname, ragtype, description, image_url, created_at
                FROM domainelementproperties
                WHERE propertyname = ? 
                AND (ragtype = ? OR (ragtype IS NULL AND ? IS NULL))
                AND (description = ? OR (description IS NULL AND ? IS NULL))
                AND (image_url = ? OR (image_url IS NULL AND ? IS NULL))
                AND (element_id = ? OR (element_id IS NULL AND ? IS NULL))
                ORDER BY id ASC
            ''', (propertyname, ragtype, ragtype, description, description, image_url, image_url, element_id, element_id))
        else:
            cur.execute('''
                SELECT id, element_id, propertyname, ragtype, description, image_url, created_at
                FROM domainelementproperties
                WHERE propertyname = ? 
                AND (ragtype = ? OR (ragtype IS NULL AND ? IS NULL))
                AND (description = ? OR (description IS NULL AND ? IS NULL))
                AND (image_url = ? OR (image_url IS NULL AND ? IS NULL))
                ORDER BY id ASC
            ''', (propertyname, ragtype, ragtype, description, description, image_url, image_url))
        
        return cur.fetchall()
    except Exception as e:
        print(f"Error getting duplicate records: {e}")
        return []
    finally:
        conn.close()

def delete_duplicates(keep_oldest=True, include_element_id=False, dry_run=True):
    """Delete duplicate records, keeping the oldest (or newest) one"""
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cur = conn.cursor()
        duplicates = find_duplicates(include_element_id)
        
        if not duplicates:
            print("No duplicates found!")
            return
        
        print(f"\nFound {len(duplicates)} duplicate groups:")
        print("=" * 80)
        
        total_deleted = 0
        
        for dup in duplicates:
            if include_element_id:
                propertyname, ragtype, description, image_url, element_id, count = dup
            else:
                propertyname, ragtype, description, image_url, count = dup
                element_id = None
            
            print(f"\nDuplicate group ({count} records):")
            print(f"  Property Name: {propertyname}")
            print(f"  RAG Type: {ragtype}")
            print(f"  Description: {description}")
            print(f"  Image URL: {image_url}")
            if include_element_id:
                print(f"  Element ID: {element_id}")
            
            # Get all records in this duplicate group
            records = get_duplicate_records(propertyname, ragtype, description, image_url, element_id)
            
            if len(records) <= 1:
                continue
            
            # Keep the first (oldest) or last (newest) record
            if keep_oldest:
                keep_record = records[0]
                delete_records = records[1:]
            else:
                keep_record = records[-1]
                delete_records = records[:-1]
            
            print(f"  Keeping record ID: {keep_record['id']} (created: {keep_record['created_at']})")
            print(f"  Deleting {len(delete_records)} duplicate(s):")
            
            for record in delete_records:
                print(f"    - ID: {record['id']} (created: {record['created_at']})")
                
                if not dry_run:
                    # Check if this property is used in canvas_property_instances
                    cur.execute('''
                        SELECT COUNT(*) FROM canvas_property_instances 
                        WHERE property_id = ?
                    ''', (record['id'],))
                    usage_count = cur.fetchone()[0]
                    
                    if usage_count > 0:
                        print(f"      WARNING: This property is used in {usage_count} canvas instance(s). Skipping deletion.")
                        continue
                    
                    # Delete the duplicate record
                    cur.execute('DELETE FROM domainelementproperties WHERE id = ?', (record['id'],))
                    total_deleted += 1
            
            print()
        
        if not dry_run:
            conn.commit()
            print(f"\nSUCCESS: Deleted {total_deleted} duplicate record(s)")
        else:
            # Calculate total that would be deleted
            would_delete = 0
            for dup in duplicates:
                if include_element_id:
                    propertyname, ragtype, description, image_url, element_id, count = dup
                else:
                    propertyname, ragtype, description, image_url, count = dup
                    element_id = None
                records = get_duplicate_records(propertyname, ragtype, description, image_url, element_id)
                would_delete += len(records) - 1  # Keep one, delete the rest
            
            print(f"\n[DRY RUN] Would delete {would_delete} duplicate record(s)")
            print("\nTo actually delete duplicates, run with --execute flag")
        
    except Exception as e:
        print(f"Error deleting duplicates: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback()
    finally:
        conn.close()

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Remove duplicate properties from domainelementproperties table')
    parser.add_argument('--execute', action='store_true', help='Actually delete duplicates (default is dry run)')
    parser.add_argument('--include-element-id', action='store_true', help='Consider element_id when identifying duplicates')
    parser.add_argument('--keep-newest', action='store_true', help='Keep newest record instead of oldest')
    parser.add_argument('--db-path', default='domainmodel.db', help='Path to database file')
    
    args = parser.parse_args()
    
    global DB_PATH
    DB_PATH = args.db_path
    
    print("=" * 80)
    print("Duplicate Property Removal Tool")
    print("=" * 80)
    
    if args.execute:
        print("\nWARNING: EXECUTE MODE: Duplicates will be permanently deleted!")
        response = input("Are you sure you want to proceed? (yes/no): ")
        if response.lower() != 'yes':
            print("Cancelled.")
            return
    else:
        print("\n[DRY RUN MODE] No changes will be made. Use --execute to actually delete.")
    
    delete_duplicates(
        keep_oldest=not args.keep_newest,
        include_element_id=args.include_element_id,
        dry_run=not args.execute
    )

if __name__ == '__main__':
    main()

