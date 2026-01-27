# SQLite Migration Guide

This guide outlines the steps to migrate from Neon PostgreSQL to SQLite.

## Overview

The application currently uses PostgreSQL (via Neon) with `psycopg2`. We'll migrate to SQLite using Python's built-in `sqlite3` module.

## Database Tables Identified

Based on the codebase analysis, the following tables exist:

1. **domainmodel** - Main elements table
2. **domainmodelrelationship** - Relationships between elements
3. **domainelementproperties** - Properties/tags for elements
4. **plantumldiagrams** - Saved PlantUML diagrams
5. **plantumldiagram_elements** - Junction table linking diagrams to elements

## Step-by-Step Migration Plan

### Step 1: Update Imports and Dependencies

**File: `server.py`**
- Remove: `import psycopg2`
- Add: `import sqlite3`
- Update requirements.txt: Remove `psycopg2-binary==2.9.9`

### Step 2: Update Database Connection Function

**Current:**
```python
def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None
```

**New:**
```python
import sqlite3
import os

# SQLite database file path
DB_PATH = os.getenv('DB_PATH', 'domainmodel.db')

def get_db_connection():
    """Create and return a SQLite database connection"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row  # Enable dict-like access
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None
```

### Step 3: Create Database Initialization Function

Add a function to create all tables if they don't exist:

```python
def init_database():
    """Initialize SQLite database with all required tables"""
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cur = conn.cursor()
        
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
        
        # Create indexes for better performance
        cur.execute('CREATE INDEX IF NOT EXISTS idx_domainmodel_enterprise ON domainmodel(enterprise)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_domainmodel_facet ON domainmodel(facet)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_relationship_source ON domainmodelrelationship(source_element_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_relationship_target ON domainmodelrelationship(target_element_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_properties_element ON domainelementproperties(element_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_diagram_elements_diagram ON plantumldiagram_elements(diagram_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_diagram_elements_element ON plantumldiagram_elements(element_id)')
        
        conn.commit()
        cur.close()
        conn.close()
        print("[Database] SQLite database initialized successfully")
        return True
    except Exception as e:
        print(f"[Database] Error initializing database: {e}")
        if conn:
            conn.close()
        return False
```

### Step 4: Update SQL Query Syntax

**Key Changes Required:**

1. **Parameter Placeholders**: Change `%s` to `?`
   ```python
   # PostgreSQL
   cur.execute('SELECT * FROM domainmodel WHERE id = %s', (record_id,))
   
   # SQLite
   cur.execute('SELECT * FROM domainmodel WHERE id = ?', (record_id,))
   ```

2. **RETURNING Clause**: Replace with `lastrowid` pattern
   ```python
   # PostgreSQL
   cur.execute('INSERT INTO domainmodel (...) VALUES (...) RETURNING *', values)
   record = dict(zip(columns, cur.fetchone()))
   
   # SQLite
   cur.execute('INSERT INTO domainmodel (...) VALUES (...)', values)
   conn.commit()
   record_id = cur.lastrowid
   cur.execute('SELECT * FROM domainmodel WHERE id = ?', (record_id,))
   record = dict(zip([desc[0] for desc in cur.description], cur.fetchone()))
   ```

3. **Remove Double Quotes**: SQLite doesn't need them
   ```python
   # PostgreSQL
   cur.execute('SELECT * FROM "domainmodel"')
   
   # SQLite
   cur.execute('SELECT * FROM domainmodel')
   ```

4. **ON CONFLICT**: SQLite uses different syntax
   ```python
   # PostgreSQL
   ON CONFLICT (diagram_id, element_id) DO NOTHING
   
   # SQLite
   INSERT OR IGNORE INTO plantumldiagram_elements (...)
   ```

5. **CURRENT_TIMESTAMP**: Works the same in SQLite

### Step 5: Update All Database Queries

**Files to Update:**
- All routes in `server.py` that use `get_db_connection()`
- Approximately 30+ locations need updates

**Pattern to Follow:**
```python
# Find all occurrences of:
cur.execute('... %s ...', (params,))
# Replace with:
cur.execute('... ? ...', (params,))

# Find all occurrences of:
RETURNING *
# Replace with lastrowid pattern

# Find all occurrences of:
FROM "domainmodel"
# Replace with:
FROM domainmodel
```

### Step 6: Handle Row Factory for Dict Access

SQLite returns tuples by default. To maintain compatibility:

```python
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row  # This enables dict-like access
```

Then access rows like:
```python
row['column_name']  # Works with Row factory
```

### Step 7: Update Requirements.txt

```txt
flask==3.0.0
flask-cors==4.0.0
requests
ddgs
# Remove: psycopg2-binary==2.9.9
```

### Step 8: Add Database Initialization on Startup

Add to the end of `server.py` before `if __name__ == '__main__':`:

```python
# Initialize database on startup
if __name__ == '__main__':
    print("[Server] Initializing SQLite database...")
    init_database()
    print("[Server] Starting Flask server...")
    app.run(host='0.0.0.0', port=5000, debug=True)
```

## Migration Checklist

- [ ] Update imports (remove psycopg2, add sqlite3)
- [ ] Update get_db_connection() function
- [ ] Create init_database() function with all table schemas
- [ ] Replace all `%s` with `?` in SQL queries
- [ ] Replace all `RETURNING *` with lastrowid pattern
- [ ] Remove double quotes from table names
- [ ] Update ON CONFLICT clauses
- [ ] Update requirements.txt
- [ ] Add database initialization on startup
- [ ] Test all CRUD operations
- [ ] Test relationships
- [ ] Test properties
- [ ] Test diagram saving/loading
- [ ] Test chatbot functionality

## Testing Steps

1. **Test Element CRUD:**
   - Create element
   - Read elements
   - Update element (if applicable)
   - Delete element

2. **Test Relationships:**
   - Create relationship
   - Read relationships
   - Delete relationship

3. **Test Properties:**
   - Add property to element
   - Read properties
   - Delete property

4. **Test Diagrams:**
   - Save diagram
   - Load diagram
   - List diagrams

5. **Test Chatbot:**
   - Query elements
   - Generate tables
   - Test image loading

## Important Notes

1. **Data Migration**: If you have existing data in Neon, you'll need to export it and import into SQLite separately.

2. **Concurrency**: SQLite handles concurrency differently than PostgreSQL. For this single-user application, this should be fine.

3. **Transactions**: SQLite supports transactions, but you need to call `conn.commit()` explicitly.

4. **Data Types**: SQLite is more flexible with types. TEXT works for VARCHAR, INTEGER for INT, etc.

5. **Foreign Keys**: SQLite has foreign keys but they're disabled by default. Enable with:
   ```python
   conn.execute('PRAGMA foreign_keys = ON')
   ```

## Rollback Plan

If migration fails:
1. Keep backup of original `server.py`
2. Keep Neon database connection string
3. Can switch back by reverting changes

