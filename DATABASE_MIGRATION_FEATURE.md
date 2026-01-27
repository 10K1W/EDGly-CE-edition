# Database Migration Feature

## Overview
The production app now automatically copies elements and relationships from the development database (`domainmodel.db`) when creating a new production database. This ensures that all your existing data is available in the production version without manual intervention.

## How It Works

### Automatic Detection
When the production app initializes a new database (first run), it:
1. Checks if the production database is empty
2. If empty, searches for `domainmodel.db` in multiple locations:
   - **Executable directory** (if running as .exe)
   - **PyInstaller temp directory** (`sys._MEIPASS`)
   - **Script directory** (if running as script)
   - **Current working directory**
3. If found, automatically copies:
   - All elements from `domainmodel` table
   - All relationships from `domainmodelrelationship` table
   - All properties from `domainelementproperties` table

### ID Mapping
The migration function maintains referential integrity by:
- Creating a mapping of old element IDs to new element IDs
- Updating all foreign key references in relationships and properties
- Preserving all data relationships

## Implementation Details

### Function: `copy_dev_database_data()`
Located in `server.py`, this function:
- Connects to the development database
- Reads all elements, relationships, and properties
- Inserts them into the production database with proper ID mapping
- Provides console feedback on the migration progress

### Integration
The function is called automatically from `init_database()` when:
- The production database is newly created (empty)
- A development database is found in one of the search locations

## Usage Scenarios

### Scenario 1: Development to Production (Same Machine)
1. Build the executable using `build_exe.bat`
2. Copy `domainmodel.db` to the same directory as the executable (optional)
3. Run the executable
4. The production database will be created in `%APPDATA%\EDGY_Repository_Modeller\`
5. Data will be automatically copied from the dev database

### Scenario 2: Distribution to New Machine
1. Build the executable
2. Optionally include `domainmodel.db` in the distribution package
3. Place both files in the same directory
4. Run the executable
5. Data will be automatically migrated

### Scenario 3: Fresh Install (No Dev Database)
1. Run the executable without a dev database present
2. A fresh, empty database will be created
3. User can start adding data from scratch

## Console Output

When migration occurs, you'll see output like:
```
[Database] Copying 25 elements from development database...
[Database] Copied 25 elements
[Database] Copied 18 relationships
[Database] Copied 12 properties
[Database] Successfully copied data from development database: C:\path\to\domainmodel.db
```

If no dev database is found:
```
[Database] No development database found to copy from
```

## Including Dev Database in Build

### Option 1: Manual Copy
Simply copy `domainmodel.db` to the same directory as the executable after building.

### Option 2: Build Script Inclusion
To automatically include the dev database in the build, edit `build.spec`:

```python
# In build.spec, uncomment these lines:
if os.path.exists('domainmodel.db'):
    datas.append(('domainmodel.db', '.'))
```

Then rebuild using `pyinstaller build.spec --clean`

## Error Handling

The migration function includes comprehensive error handling:
- **Database not found**: Gracefully continues with empty database
- **Empty dev database**: Skips migration
- **Missing foreign keys**: Skips invalid relationships/properties with warning
- **SQL errors**: Logs error and continues initialization

## Production Database Location

The production database is stored in:
- **Windows**: `%APPDATA%\EDGY_Repository_Modeller\domainmodel.db`
- This ensures:
  - User-specific data storage
  - Proper permissions
  - No conflicts with development database

## Benefits

1. **Seamless Migration**: No manual data export/import required
2. **Automatic**: Happens transparently on first run
3. **Safe**: Only copies when production DB is empty
4. **Flexible**: Works with or without dev database present
5. **Robust**: Handles missing data gracefully

## Testing

To test the migration feature:
1. Ensure you have a `domainmodel.db` with data
2. Delete or rename the production database: `%APPDATA%\EDGY_Repository_Modeller\domainmodel.db`
3. Run the executable
4. Verify data was copied by checking the console output
5. Verify data in the application UI

## Future Enhancements

Potential improvements:
- Migration version tracking
- Selective data migration (by enterprise, facet, etc.)
- Migration from multiple source databases
- Data validation and conflict resolution
- Migration rollback capability

