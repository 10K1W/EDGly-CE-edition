#!/usr/bin/env python3
import sqlite3

conn = sqlite3.connect('domainmodel.db')
cur = conn.cursor()
cur.execute('PRAGMA table_info(domainelementproperties)')
columns = cur.fetchall()
print("Current schema:")
for col in columns:
    notnull = "NOT NULL" if col[3] else "NULLABLE"
    print(f"  {col[1]}: {notnull}")
conn.close()

