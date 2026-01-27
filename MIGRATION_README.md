# Data Migration Guide: Neon PostgreSQL → SQLite

This guide explains how to migrate your existing data from Neon PostgreSQL to the new SQLite database.

## Prerequisites

1. **Install psycopg2-binary** (temporarily needed for migration):
   ```bash
   pip install psycopg2-binary
   ```
   
   Or install all requirements:
   ```bash
   pip install -r requirements.txt
   ```

2. **Ensure Neon database is accessible** - The script uses the connection string from your environment or the default one in the script.

## Running the Migration

1. **Run the migration script**:
   ```bash
   python migrate_to_sqlite.py
   ```

2. **The script will**:
   - Connect to your Neon PostgreSQL database
   - Connect to (or create) the SQLite database (`domainmodel.db`)
   - Initialize SQLite tables if they don't exist
   - Copy all data from Neon to SQLite in the correct order:
     - First: `domainmodel` and `plantumldiagrams` (base tables)
     - Then: `domainmodelrelationship`, `domainelementproperties`, `plantumldiagram_elements` (dependent tables)
   - Verify the migration by comparing row counts
   - Reset SQLite sequences to continue from the highest IDs

3. **If SQLite database already has data**, the script will ask for confirmation before proceeding.

## What Gets Migrated

All tables and their data:
- ✅ `domainmodel` - All elements
- ✅ `domainmodelrelationship` - All relationships
- ✅ `domainelementproperties` - All element properties
- ✅ `plantumldiagrams` - All saved diagrams
- ✅ `plantumldiagram_elements` - All diagram-element links

## After Migration

1. **Verify the migration** - The script shows a summary with row counts for each table.

2. **Test the application**:
   ```bash
   python server.py
   ```

3. **Optional: Remove psycopg2-binary** after migration (if you don't need it):
   ```bash
   pip uninstall psycopg2-binary
   ```
   
   Or remove it from `requirements.txt` if you've already migrated.

## Troubleshooting

**Error: "Failed to connect to Neon database"**
- Check your internet connection
- Verify the Neon database connection string is correct
- Check if the Neon database is accessible

**Error: "Failed to connect to SQLite database"**
- Check file permissions in the project directory
- Ensure you have write access to create `domainmodel.db`

**Warning: "Skipping duplicate row"**
- This is normal if you run the migration multiple times
- The script skips rows that would violate unique constraints

**Foreign key constraint errors**
- The script migrates tables in the correct order to avoid this
- If you see these errors, check that all parent records exist

## Notes

- The migration preserves all IDs from Neon
- Timestamps are preserved exactly as they were
- The SQLite database file (`domainmodel.db`) will be created in the project root
- You can run the migration multiple times safely (duplicates will be skipped)

