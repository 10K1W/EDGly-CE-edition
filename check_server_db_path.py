#!/usr/bin/env python3
import os
import sys

# Simulate server.py logic
if getattr(sys, 'frozen', False):
    app_data = os.getenv('APPDATA')
    if app_data:
        db_path = os.path.join(app_data, 'EDGY_Repository_Modeller', 'domainmodel.db')
    else:
        db_path = 'domainmodel.db'
else:
    db_path = os.getenv('DB_PATH', 'domainmodel.db')

print(f"Server would use DB path: {db_path}")
print(f"DB exists: {os.path.exists(db_path)}")

if os.path.exists(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('PRAGMA table_info(domainelementproperties)')
    columns = cur.fetchall()
    print("\nSchema in server DB:")
    for col in columns:
        notnull = "NOT NULL" if col[3] else "NULLABLE"
        print(f"  {col[1]}: {notnull}")
    conn.close()

