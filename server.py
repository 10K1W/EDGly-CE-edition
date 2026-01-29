#!/usr/bin/env python3
"""
Simple standalone server for DomainModel UI
Requires: pip install flask requests ddgs
SQLite is built into Python, no additional package needed.
"""

from flask import Flask, request, jsonify, send_from_directory, g, has_app_context
from flask_cors import CORS
import sqlite3
import os
import sys
import uuid
import secrets
import hashlib
import hmac
from datetime import datetime, timedelta
import zlib
import base64
import logging
import math
from collections import deque
from urllib.parse import urlparse
import json

app = Flask(__name__, static_folder='.')
app.static_folder = 'public'
CORS(app)

def setup_logging():
    """Configure file logging early so startup failures are captured."""
    base_dir = os.getenv('APPDATA') or os.getcwd()
    log_dir = os.path.join(base_dir, 'EDGY_Repository_Modeller', 'logs')
    log_path = os.path.join(log_dir, 'edgy_server.log')
    try:
        os.makedirs(log_dir, exist_ok=True)
        handlers = [
            logging.FileHandler(log_path, encoding='utf-8'),
            logging.StreamHandler()
        ]
    except Exception:
        handlers = [logging.StreamHandler()]
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=handlers
    )
    logging.info("Logging initialized: %s", log_path)

setup_logging()

# SQLite database file path
# Handle both development and production (PyInstaller) environments
if getattr(sys, 'frozen', False):
    # Running as compiled executable - use AppData directory
    APP_DATA_DIR = os.path.join(os.getenv('APPDATA'), 'EDGY_Repository_Modeller')
else:
    # Running as script - use current directory unless overridden
    APP_DATA_DIR = os.getenv('EDGY_APP_DATA', os.getcwd())

os.makedirs(APP_DATA_DIR, exist_ok=True)
DB_PATH = os.getenv('DB_PATH', os.path.join(APP_DATA_DIR, 'domainmodel.db'))

AUTH_DB_PATH = os.getenv('AUTH_DB_PATH', os.path.join(APP_DATA_DIR, 'auth.db'))
USER_DB_DIR = os.getenv('USER_DB_DIR', os.path.join(APP_DATA_DIR, 'user_dbs'))
AUTH_TOKEN_TTL_HOURS = int(os.getenv('AUTH_TOKEN_TTL_HOURS', '24'))
AUTH_REQUIRED = os.getenv('AUTH_REQUIRED', 'true').lower() != 'false'
CE_LIMITS_ENABLED = os.getenv('CE_LIMITS_ENABLED', 'true').lower() != 'false'
CE_MAX_MODELS = int(os.getenv('CE_MAX_MODELS', '5'))
CE_MAX_ELEMENT_OCCURRENCES = int(os.getenv('CE_MAX_ELEMENT_OCCURRENCES', '200'))

def get_db_connection(db_path=None):
    """Create and return a SQLite database connection"""
    try:
        resolved_path = db_path
        if resolved_path is None and has_app_context():
            resolved_path = getattr(g, 'user_db_path', None)
        if not resolved_path:
            resolved_path = DB_PATH
        # Use check_same_thread=False to allow multi-threaded access
        # Set timeout to handle locked database
        conn = sqlite3.connect(resolved_path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # Enable dict-like access
        # Enable foreign keys
        conn.execute('PRAGMA foreign_keys = ON')
        # Set busy timeout
        conn.execute('PRAGMA busy_timeout = 10000')  # 10 seconds
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        import traceback
        traceback.print_exc()
        return None

def get_auth_connection():
    """Create and return a SQLite connection for auth data"""
    try:
        conn = sqlite3.connect(AUTH_DB_PATH, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('PRAGMA busy_timeout = 10000')
        return conn
    except Exception as e:
        print(f"Auth database connection error: {e}")
        import traceback
        traceback.print_exc()
        return None

def init_auth_database():
    """Initialize auth database tables"""
    conn = get_auth_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT,
                company_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login_at TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON user_sessions(user_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON user_sessions(token_hash)')
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[Auth] Error initializing auth database: {e}")
        if conn:
            conn.close()
        return False

def hash_password(password):
    salt = secrets.token_bytes(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 120000)
    return f"{base64.b64encode(salt).decode('utf-8')}${base64.b64encode(hashed).decode('utf-8')}"

def verify_password(password, stored_hash):
    try:
        salt_b64, hash_b64 = stored_hash.split('$', 1)
        salt = base64.b64decode(salt_b64.encode('utf-8'))
        expected = base64.b64decode(hash_b64.encode('utf-8'))
    except Exception:
        return False
    computed = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 120000)
    return hmac.compare_digest(computed, expected)

def hash_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def create_session(conn, user_id):
    token = secrets.token_urlsafe(32)
    token_hash = hash_token(token)
    session_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(hours=AUTH_TOKEN_TTL_HOURS)
    conn.execute('''
        INSERT INTO user_sessions (id, user_id, token_hash, expires_at)
        VALUES (?, ?, ?, ?)
    ''', (session_id, user_id, token_hash, expires_at.isoformat()))
    return token

def extract_bearer_token():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header:
        return None
    parts = auth_header.split(' ')
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return None
    return parts[1].strip()

def ensure_seeded_user_database(user_db_path):
    """Ensure a user database has seed elements/relationships/properties."""
    conn = get_db_connection(db_path=user_db_path)
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM domainmodel')
        element_count = cur.fetchone()[0]
        if element_count == 0 and DB_PATH and os.path.exists(DB_PATH):
            copy_seed_database_data(conn, DB_PATH)
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[Database] Error ensuring seed data: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return False

def ensure_user_database(user_id):
    os.makedirs(USER_DB_DIR, exist_ok=True)
    user_db_path = os.path.join(USER_DB_DIR, f"user_{user_id}.db")
    if not os.path.exists(user_db_path):
        init_database(db_path=user_db_path)
    else:
        ensure_seeded_user_database(user_db_path)
    return user_db_path

def resolve_auth_user(token):
    if not token:
        return None
    token_hash = hash_token(token)
    conn = get_auth_connection()
    if not conn:
        return None
    cur = conn.cursor()
    cur.execute('''
        SELECT s.user_id, s.expires_at, u.email, u.full_name, u.is_active
        FROM user_sessions s
        JOIN users u ON s.user_id = u.id
        WHERE s.token_hash = ?
    ''', (token_hash,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return None
    expires_at = datetime.fromisoformat(row['expires_at'])
    if expires_at < datetime.utcnow() or not row['is_active']:
        cur.execute('DELETE FROM user_sessions WHERE token_hash = ?', (token_hash,))
        conn.commit()
        cur.close()
        conn.close()
        return None
    cur.execute('UPDATE user_sessions SET last_used_at = CURRENT_TIMESTAMP WHERE token_hash = ?', (token_hash,))
    conn.commit()
    cur.close()
    conn.close()
    return {
        'user_id': row['user_id'],
        'email': row['email'],
        'full_name': row['full_name']
    }

def enforce_model_limit(conn, models_to_add=1):
    if not CE_LIMITS_ENABLED or CE_MAX_MODELS <= 0:
        return True, None
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM canvas_models')
    total_models = cur.fetchone()[0]
    cur.close()
    if total_models + models_to_add > CE_MAX_MODELS:
        return False, {
            'error': 'Model limit reached',
            'limit': CE_MAX_MODELS,
            'current': total_models
        }
    return True, None

def enforce_element_occurrence_limit(conn, occurrences_to_add=1, current_delta=0):
    if not CE_LIMITS_ENABLED or CE_MAX_ELEMENT_OCCURRENCES <= 0:
        return True, None
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM canvas_element_instances')
    total_occurrences = cur.fetchone()[0]
    cur.close()
    projected_total = total_occurrences + occurrences_to_add + current_delta
    if projected_total > CE_MAX_ELEMENT_OCCURRENCES:
        return False, {
            'error': 'Element occurrence limit reached',
            'limit': CE_MAX_ELEMENT_OCCURRENCES,
            'current': total_occurrences
        }
    return True, None

@app.before_request
def enforce_authentication():
    if not AUTH_REQUIRED:
        return None
    if not request.path.startswith('/api/'):
        return None
    if request.path in ('/api/auth/register', '/api/auth/login'):
        return None
    token = extract_bearer_token()
    user = resolve_auth_user(token)
    if not user:
        return jsonify({'error': 'Authentication required'}), 401
    g.current_user_id = user['user_id']
    g.current_user_email = user['email']
    g.current_user_full_name = user.get('full_name')
    g.user_db_path = ensure_user_database(user['user_id'])
    return None

def init_database(db_path=None):
    """Initialize SQLite database with all required tables"""
    if not init_auth_database():
        return False
    conn = get_db_connection(db_path=db_path)
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
        # Note: element_id can be NULL for template properties that can be used with any element
        cur.execute('''
            CREATE TABLE IF NOT EXISTS domainelementproperties (
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
        
        # Migrate existing schema if element_id was NOT NULL
        # SQLite doesn't support ALTER TABLE to change NOT NULL constraints easily
        # So we'll check and recreate the table if needed
        try:
            cur.execute('PRAGMA table_info(domainelementproperties)')
            columns = cur.fetchall()
            element_id_col = next((col for col in columns if col[1] == 'element_id'), None)
            if element_id_col and element_id_col[3] == 1:  # notnull = 1 means NOT NULL
                # Table exists with NOT NULL constraint - need to migrate
                print("[Database] Migrating domainelementproperties table to allow NULL element_id...")
                # Create a temporary table with the new schema
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
                # Copy data from old table
                cur.execute('''
                    INSERT INTO domainelementproperties_new 
                    (id, element_id, ragtype, propertyname, description, image_url, created_at, updated_at)
                    SELECT id, element_id, ragtype, propertyname, description, image_url, created_at, updated_at
                    FROM domainelementproperties
                ''')
                # Drop old table and rename new one
                cur.execute('DROP TABLE domainelementproperties')
                cur.execute('ALTER TABLE domainelementproperties_new RENAME TO domainelementproperties')
                # Recreate indexes after migration
                cur.execute('CREATE INDEX IF NOT EXISTS idx_properties_element ON domainelementproperties(element_id)')
                conn.commit()
                print("[Database] Migration completed successfully")
        except Exception as e:
            # If migration fails, table might already be correct or migration not needed
            print(f"[Database] Property table migration check: {e}")
            pass
        
        # Migrate existing schema if element_id was NOT NULL
        # Check if we need to alter the table to allow NULL
        try:
            cur.execute('PRAGMA table_info(domainelementproperties)')
            columns = cur.fetchall()
            element_id_col = next((col for col in columns if col[1] == 'element_id'), None)
            if element_id_col and element_id_col[3] == 1:  # notnull = 1 means NOT NULL
                # Table exists with NOT NULL constraint, we can't easily alter it in SQLite
                # But new inserts will work if we provide NULL or a value
                pass
        except:
            pass
        
        # Create audit_log table for change tracking
        cur.execute('''
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                user_name TEXT,
                old_value TEXT,
                new_value TEXT,
                change_summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create element_versions table for version history
        cur.execute('''
            CREATE TABLE IF NOT EXISTS element_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                element_id INTEGER NOT NULL,
                version_number INTEGER NOT NULL,
                name TEXT,
                description TEXT,
                enterprise TEXT,
                facet TEXT,
                element TEXT,
                image_url TEXT,
                created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (element_id) REFERENCES domainmodel(id),
                UNIQUE(element_id, version_number)
            )
        ''')
        
        # Create canvas_models table for drag-and-drop modeling canvas
        cur.execute('''
            CREATE TABLE IF NOT EXISTS canvas_models (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                canvas_width INTEGER DEFAULT 2000,
                canvas_height INTEGER DEFAULT 2000,
                zoom_level REAL DEFAULT 1.0,
                pan_x REAL DEFAULT 0,
                pan_y REAL DEFAULT 0,
                canvas_template TEXT DEFAULT 'none',
                template_zoom REAL DEFAULT 1.0,
                template_pan_x REAL DEFAULT 0,
                template_pan_y REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Add template columns if they don't exist (migration)
        try:
            cur.execute('PRAGMA table_info(canvas_models)')
            columns = [col[1] for col in cur.fetchall()]
            if 'canvas_template' not in columns:
                cur.execute('ALTER TABLE canvas_models ADD COLUMN canvas_template TEXT DEFAULT \'none\'')
            if 'template_zoom' not in columns:
                cur.execute('ALTER TABLE canvas_models ADD COLUMN template_zoom REAL DEFAULT 1.0')
            if 'template_pan_x' not in columns:
                cur.execute('ALTER TABLE canvas_models ADD COLUMN template_pan_x REAL DEFAULT 0')
            if 'template_pan_y' not in columns:
                cur.execute('ALTER TABLE canvas_models ADD COLUMN template_pan_y REAL DEFAULT 0')
        except Exception as e:
            print(f"[Database] Template columns migration: {e}")
        
        # Create canvas_template_segments table for Milkyway template segments
        cur.execute('''
            CREATE TABLE IF NOT EXISTS canvas_template_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canvas_model_id INTEGER NOT NULL,
                segment_index INTEGER NOT NULL,
                segment_name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (canvas_model_id) REFERENCES canvas_models(id) ON DELETE CASCADE,
                UNIQUE(canvas_model_id, segment_index)
            )
        ''')
        
        # Create canvas_element_segment_associations table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS canvas_element_segment_associations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canvas_model_id INTEGER NOT NULL,
                element_instance_id INTEGER NOT NULL,
                segment_index INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (canvas_model_id) REFERENCES canvas_models(id) ON DELETE CASCADE,
                FOREIGN KEY (element_instance_id) REFERENCES canvas_element_instances(id) ON DELETE CASCADE,
                UNIQUE(canvas_model_id, element_instance_id)
            )
        ''')
        
        # Create canvas_element_instances table for element instances on canvas
        cur.execute('''
            CREATE TABLE IF NOT EXISTS canvas_element_instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canvas_model_id INTEGER NOT NULL,
                element_type_id INTEGER NOT NULL,
                instance_name TEXT NOT NULL,
                description TEXT,
                x_position REAL NOT NULL,
                y_position REAL NOT NULL,
                width INTEGER DEFAULT 120,
                height INTEGER DEFAULT 120,
                z_index INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (canvas_model_id) REFERENCES canvas_models(id) ON DELETE CASCADE,
                FOREIGN KEY (element_type_id) REFERENCES domainmodel(id)
            )
        ''')
        
        # Add description column if it doesn't exist (migration)
        try:
            cur.execute('PRAGMA table_info(canvas_element_instances)')
            columns = [col[1] for col in cur.fetchall()]
            if 'description' not in columns:
                cur.execute('ALTER TABLE canvas_element_instances ADD COLUMN description TEXT')
        except Exception as e:
            print(f"[Database] Description column migration: {e}")
        
        # Create canvas_relationships table for visual relationships on canvas
        cur.execute('''
            CREATE TABLE IF NOT EXISTS canvas_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canvas_model_id INTEGER NOT NULL,
                source_instance_id INTEGER NOT NULL,
                target_instance_id INTEGER NOT NULL,
                relationship_type TEXT,
                line_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (canvas_model_id) REFERENCES canvas_models(id) ON DELETE CASCADE,
                FOREIGN KEY (source_instance_id) REFERENCES canvas_element_instances(id) ON DELETE CASCADE,
                FOREIGN KEY (target_instance_id) REFERENCES canvas_element_instances(id) ON DELETE CASCADE
            )
        ''')
        
        # Create canvas_property_instances table for property instances on canvas
        cur.execute('''
            CREATE TABLE IF NOT EXISTS canvas_property_instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canvas_model_id INTEGER NOT NULL,
                property_id INTEGER NOT NULL,
                element_instance_id INTEGER NOT NULL,
                instance_name TEXT NOT NULL,
                x_position REAL NOT NULL,
                y_position REAL NOT NULL,
                width INTEGER DEFAULT 100,
                height INTEGER DEFAULT 30,
                z_index INTEGER DEFAULT 0,
                source TEXT,
                rule_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (canvas_model_id) REFERENCES canvas_models(id) ON DELETE CASCADE,
                FOREIGN KEY (property_id) REFERENCES domainelementproperties(id),
                FOREIGN KEY (element_instance_id) REFERENCES canvas_element_instances(id) ON DELETE CASCADE
            )
        ''')
        
        # Add source/rule_id columns to canvas_property_instances if they don't exist
        try:
            cur.execute('PRAGMA table_info(canvas_property_instances)')
            columns = [col[1] for col in cur.fetchall()]
            if 'source' not in columns:
                cur.execute('ALTER TABLE canvas_property_instances ADD COLUMN source TEXT')
            if 'rule_id' not in columns:
                cur.execute('ALTER TABLE canvas_property_instances ADD COLUMN rule_id INTEGER')
        except Exception as e:
            print(f"[Database] canvas_property_instances migration: {e}")
        
        # Create design_rules table for smart analytics rules
        cur.execute('''
            CREATE TABLE IF NOT EXISTS design_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                rule_type TEXT NOT NULL,
                subject_element_type TEXT NOT NULL,
                relationship_type TEXT,
                target_element_type TEXT,
                conditions_json TEXT,
                active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Ensure conditions_json exists and drop legacy rule fields if present
        try:
            cur.execute('PRAGMA table_info(design_rules)')
            columns = [col[1] for col in cur.fetchall()]
            if 'conditions_json' not in columns:
                cur.execute('ALTER TABLE design_rules ADD COLUMN conditions_json TEXT')
                conn.commit()
                columns.append('conditions_json')
                print("[Database] Added conditions_json column to design_rules table")

            legacy_columns = {
                'property_target',
                'property_name',
                'warning_threshold',
                'negative_threshold',
                'positive_threshold'
            }
            if legacy_columns.intersection(columns):
                print("[Database] Removing legacy design_rules columns...")
                cur.execute('PRAGMA foreign_keys = OFF')
                try:
                    cur.execute('''
                        CREATE TABLE design_rules_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT NOT NULL,
                            description TEXT,
                            rule_type TEXT NOT NULL,
                            subject_element_type TEXT NOT NULL,
                            relationship_type TEXT,
                            target_element_type TEXT,
                            conditions_json TEXT,
                            active BOOLEAN DEFAULT 1,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')
                    select_conditions = 'conditions_json' if 'conditions_json' in columns else 'NULL as conditions_json'
                    cur.execute(f'''
                        INSERT INTO design_rules_new
                        (id, name, description, rule_type, subject_element_type, relationship_type, target_element_type,
                         conditions_json, active, created_at, updated_at)
                        SELECT id, name, description, rule_type, subject_element_type, relationship_type, target_element_type,
                               {select_conditions}, active, created_at, updated_at
                        FROM design_rules
                    ''')
                    cur.execute('DROP TABLE design_rules')
                    cur.execute('ALTER TABLE design_rules_new RENAME TO design_rules')
                    conn.commit()
                    print("[Database] Legacy design_rules columns removed")
                finally:
                    cur.execute('PRAGMA foreign_keys = ON')
        except Exception as e:
            print(f"[Database] Migration check for design_rules: {e}")
            pass
        
        # Create design_rule_violations table for cached rule evaluation results
        cur.execute('''
            CREATE TABLE IF NOT EXISTS design_rule_violations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id INTEGER NOT NULL,
                element_instance_id INTEGER NOT NULL,
                severity TEXT NOT NULL,
                current_value INTEGER NOT NULL,
                threshold_value INTEGER NOT NULL,
                evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (rule_id) REFERENCES design_rules(id) ON DELETE CASCADE,
                FOREIGN KEY (element_instance_id) REFERENCES canvas_element_instances(id) ON DELETE CASCADE
            )
        ''')
        
        # Create indexes for better performance
        cur.execute('CREATE INDEX IF NOT EXISTS idx_domainmodel_enterprise ON domainmodel(enterprise)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_domainmodel_facet ON domainmodel(facet)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_relationship_source ON domainmodelrelationship(source_element_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_relationship_target ON domainmodelrelationship(target_element_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_properties_element ON domainelementproperties(element_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_canvas_instances_model ON canvas_element_instances(canvas_model_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_canvas_instances_type ON canvas_element_instances(element_type_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_canvas_relationships_model ON canvas_relationships(canvas_model_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_canvas_relationships_source ON canvas_relationships(source_instance_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_canvas_relationships_target ON canvas_relationships(target_instance_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_canvas_property_instances_model ON canvas_property_instances(canvas_model_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_canvas_property_instances_element ON canvas_property_instances(element_instance_id)')
        # Indexes for design rules
        cur.execute('CREATE INDEX IF NOT EXISTS idx_design_rules_active ON design_rules(active)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_design_rules_subject_type ON design_rules(subject_element_type)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_design_rule_violations_rule ON design_rule_violations(rule_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_design_rule_violations_element ON design_rule_violations(element_instance_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_design_rule_violations_severity ON design_rule_violations(severity)')
        # Indexes for audit log
        cur.execute('CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at DESC)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_element_versions_element ON element_versions(element_id)')
        
        conn.commit()
        
        # Check if database is new/empty and copy data from dev database if available
        cur.execute('SELECT COUNT(*) FROM domainmodel')
        element_count = cur.fetchone()[0]
        
        if element_count == 0:
            # Database is empty, try to copy from seeded database first
            if db_path and DB_PATH and os.path.exists(DB_PATH) and db_path != DB_PATH:
                copy_seed_database_data(conn, DB_PATH)
            else:
                # Fall back to dev database discovery
                copy_dev_database_data(conn)
        
        # Initialize Process -> Process flow relationship rule if Process elements exist
        init_process_flow_relationship(conn)
        
        cur.close()
        conn.close()
        print("[Database] SQLite database initialized successfully")
        return True
    except Exception as e:
        print(f"[Database] Error initializing database: {e}")
        if conn:
            conn.close()
        return False

def copy_dev_database_data(target_conn):
    """
    Copy elements and relationships from development database to production database.
    This function is called when initializing a new production database.
    """
    # Find the development database path
    # Try multiple possible locations
    dev_db_paths = []
    
    if getattr(sys, 'frozen', False):
        # Running as executable - check executable directory and temp directory
        exe_dir = os.path.dirname(sys.executable)
        dev_db_paths.append(os.path.join(exe_dir, 'domainmodel.db'))
        # Also check the temp directory where PyInstaller extracts files
        try:
            meipass_dir = sys._MEIPASS
            dev_db_paths.append(os.path.join(meipass_dir, 'domainmodel.db'))
        except:
            pass
    else:
        # Running as script - check script directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        dev_db_paths.append(os.path.join(script_dir, 'domainmodel.db'))
    
    # Also check current working directory
    dev_db_paths.extend([
        os.path.join(os.getcwd(), 'domainmodel.db'),
        'domainmodel.db',
    ])
    
    dev_db_path = None
    for path in dev_db_paths:
        if os.path.exists(path) and os.path.isfile(path):
            dev_db_path = path
            break
    
    if not dev_db_path:
        print("[Database] No development database found to copy from")
        return False
    
    try:
        return copy_seed_database_data(target_conn, dev_db_path)
    except Exception as e:
        print(f"[Database] Error copying from dev database: {e}")
        return False

def copy_seed_database_data(target_conn, seed_db_path):
    """Copy elements and relationships from a known seed database."""
    if not seed_db_path or not os.path.exists(seed_db_path):
        print("[Database] Seed database not found")
        return False
    try:
        dev_conn = sqlite3.connect(seed_db_path, timeout=10.0)
        dev_conn.row_factory = sqlite3.Row
        dev_cur = dev_conn.cursor()
        
        target_cur = target_conn.cursor()
        
        # Check if dev database has data
        dev_cur.execute('SELECT COUNT(*) FROM domainmodel')
        dev_element_count = dev_cur.fetchone()[0]
        
        if dev_element_count == 0:
            print("[Database] Development database is empty, nothing to copy")
            dev_cur.close()
            dev_conn.close()
            return False
        
        print(f"[Database] Copying {dev_element_count} elements from development database...")
        
        # Copy domainmodel records
        dev_cur.execute('''
            SELECT id, name, description, enterprise, facet, element, image_url, 
                   created_at, updated_at
            FROM domainmodel
            ORDER BY id
        ''')
        dev_elements = dev_cur.fetchall()
        
        # Create ID mapping (old_id -> new_id)
        id_mapping = {}
        
        for dev_elem in dev_elements:
            old_id = dev_elem['id']
            target_cur.execute('''
                INSERT INTO domainmodel 
                (name, description, enterprise, facet, element, image_url, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                dev_elem['name'],
                dev_elem['description'],
                dev_elem['enterprise'],
                dev_elem['facet'],
                dev_elem['element'],
                dev_elem['image_url'],
                dev_elem['created_at'],
                dev_elem['updated_at']
            ))
            new_id = target_cur.lastrowid
            id_mapping[old_id] = new_id
        
        print(f"[Database] Copied {len(dev_elements)} elements")
        
        # Copy domainmodelrelationship records (with ID mapping)
        dev_cur.execute('''
            SELECT source_element_id, target_element_id, relationship_type, 
                   description, created_at, updated_at
            FROM domainmodelrelationship
        ''')
        dev_relationships = dev_cur.fetchall()
        
        relationships_copied = 0
        relationships_skipped = 0
        
        for dev_rel in dev_relationships:
            old_source_id = dev_rel['source_element_id']
            old_target_id = dev_rel['target_element_id']
            
            # Map old IDs to new IDs
            new_source_id = id_mapping.get(old_source_id)
            new_target_id = id_mapping.get(old_target_id)
            
            # Skip if IDs couldn't be mapped (shouldn't happen, but be safe)
            if not new_source_id or not new_target_id:
                relationships_skipped += 1
                continue
            
            target_cur.execute('''
                INSERT INTO domainmodelrelationship 
                (source_element_id, target_element_id, relationship_type, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                new_source_id,
                new_target_id,
                dev_rel['relationship_type'],
                dev_rel['description'],
                dev_rel['created_at'],
                dev_rel['updated_at']
            ))
            relationships_copied += 1
        
        print(f"[Database] Copied {relationships_copied} relationships")
        if relationships_skipped > 0:
            print(f"[Database] Skipped {relationships_skipped} relationships (missing element references)")
        
        # Copy domainelementproperties records (with ID mapping)
        dev_cur.execute('''
            SELECT element_id, ragtype, propertyname, description, image_url, 
                   created_at, updated_at
            FROM domainelementproperties
        ''')
        dev_properties = dev_cur.fetchall()
        
        properties_copied = 0
        properties_skipped = 0
        
        for dev_prop in dev_properties:
            old_element_id = dev_prop['element_id']
            new_element_id = id_mapping.get(old_element_id)
            
            if not new_element_id:
                properties_skipped += 1
                continue
            
            target_cur.execute('''
                INSERT INTO domainelementproperties 
                (element_id, ragtype, propertyname, description, image_url, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                new_element_id,
                dev_prop['ragtype'],
                dev_prop['propertyname'],
                dev_prop['description'],
                dev_prop['image_url'],
                dev_prop['created_at'],
                dev_prop['updated_at']
            ))
            properties_copied += 1
        
        print(f"[Database] Copied {properties_copied} properties")
        if properties_skipped > 0:
            print(f"[Database] Skipped {properties_skipped} properties (missing element references)")
        
        # Commit all changes
        target_conn.commit()
        
        dev_cur.close()
        dev_conn.close()
        
        print(f"[Database] Successfully copied data from development database: {seed_db_path}")
        return True
        
    except sqlite3.Error as e:
        print(f"[Database] Error copying from development database: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"[Database] Unexpected error copying from development database: {e}")
        import traceback
        traceback.print_exc()
        return False

def init_process_flow_relationship(conn=None):
    """Ensure Process -> Process flow relationship rule exists in database"""
    if conn is None:
        conn = get_db_connection()
        if not conn:
            return False
        should_close = True
    else:
        should_close = False
    
    try:
        cur = conn.cursor()
        
        # Check if Process -> Process flow relationship already exists
        cur.execute('''
            SELECT COUNT(*) FROM domainmodelrelationship dmr
            JOIN domainmodel dm1 ON dmr.source_element_id = dm1.id
            JOIN domainmodel dm2 ON dmr.target_element_id = dm2.id
            WHERE dm1.element = 'Process' 
            AND dm2.element = 'Process' 
            AND dmr.relationship_type = 'flow'
        ''')
        count = cur.fetchone()[0]
        
        if count > 0:
            # Relationship rule already exists
            if should_close:
                cur.close()
                conn.close()
            return True
        
        # Find Process elements
        cur.execute('SELECT id FROM domainmodel WHERE element = ? LIMIT 2', ('Process',))
        process_elements = cur.fetchall()
        
        if len(process_elements) < 1:
            # Need at least 1 Process element to create a relationship rule
            if should_close:
                cur.close()
                conn.close()
            return False
        
        # Create Process -> Process flow relationship
        # For relationship rules, self-referential relationships are allowed
        # (same Process element as both source and target)
        source_id = process_elements[0][0]
        if len(process_elements) >= 2:
            target_id = process_elements[1][0]
        else:
            # Use the same Process element for both source and target (self-referential)
            # This creates a valid relationship rule: Process -> Process flow
            target_id = process_elements[0][0]
        
        # Check if this specific relationship already exists
        cur.execute('''
            SELECT id FROM domainmodelrelationship 
            WHERE source_element_id = ? AND target_element_id = ? AND relationship_type = ?
        ''', (source_id, target_id, 'flow'))
        
        if not cur.fetchone():
            cur.execute('''
                INSERT INTO domainmodelrelationship 
                (source_element_id, target_element_id, relationship_type, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ''', (source_id, target_id, 'flow', 'Process flows to Process'))
            conn.commit()
        
        if should_close:
            cur.close()
            conn.close()
        return True
        
    except Exception as e:
        if should_close and conn:
            conn.close()
        print(f"Error initializing Process flow relationship: {e}")
        import traceback
        traceback.print_exc()
        return False

def call_gemini(prompt, max_tokens=8192):
    """
    Call Google Gemini API to generate a response.
    Uses the Gemini API with the configured API key.
    """
    try:
        import requests
    except Exception as e:
        return f"[Gemini] Missing 'requests' dependency: {e}"
    try:
        api_key = "AIzaSyDnuzH3L0Xg7MF9YmO2T3q_6IKHaVfrvfY"
        
        # Tested and working models (in order of preference)
        models_to_try = [
            "gemini-2.5-flash",      # Fast and efficient, tested and working
            "gemini-2.5-pro",        # More capable model
            "gemini-2.0-flash",      # Alternative flash model
            "gemini-2.0-flash-001"   # Specific version
        ]
        
        for model in models_to_try:
            try:
                # Gemini API endpoint - use API key as query parameter
                api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                
                headers = {
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "contents": [{
                        "parts": [{
                            "text": prompt
                        }]
                    }],
                    "generationConfig": {
                        "maxOutputTokens": max_tokens,
                        "temperature": 0.7,
                        "topP": 0.8,
                        "topK": 40
                    }
                }
                
                response = requests.post(api_url, headers=headers, json=payload, timeout=30)
                
                if response.status_code == 200:
                    result = response.json()
                    # Extract the generated text from Gemini response
                    if 'candidates' in result and len(result['candidates']) > 0:
                        candidate = result['candidates'][0]
                        if 'content' in candidate and 'parts' in candidate['content']:
                            parts = candidate['content']['parts']
                            if len(parts) > 0 and 'text' in parts[0]:
                                return parts[0]['text'].strip()
                    # If no text found, try next model
                    print(f"[Gemini] Model {model} returned unexpected response format, trying next model...")
                    continue
                elif response.status_code == 404:
                    # Model not found, try next model
                    print(f"[Gemini] Model {model} not found (404), trying next model...")
                    continue
                elif response.status_code == 429:
                    # Rate limit exceeded
                    error_text = response.text[:500] if hasattr(response, 'text') else ''
                    print(f"[Gemini] Rate limit exceeded (429) for {model}")
                    # Return a special error indicator for rate limits
                    return "QUOTA_RATE_LIMIT"
                elif response.status_code == 403:
                    # Check if it's a quota error
                    error_text = response.text[:500] if hasattr(response, 'text') else ''
                    try:
                        error_json = response.json()
                        error_obj = error_json.get('error', {})
                        error_message = error_obj.get('message', '').lower()
                        error_code = error_obj.get('code', '')
                        
                        # Check for quota-related errors
                        if 'quota' in error_message or 'quotaexceeded' in error_message or \
                           'RESOURCE_EXHAUSTED' in str(error_code) or 'quotaExceeded' in str(error_code):
                            print(f"[Gemini] Quota exceeded for {model}: {error_message}")
                            # Return a special error indicator for quota
                            return "QUOTA_EXCEEDED"
                    except:
                        pass
                    # Other 403 error, try next model
                    print(f"[Gemini] Permission denied (403) for {model}: {error_text[:200]}")
                    if model == models_to_try[-1]:
                        return "QUOTA_ERROR"
                    continue
                else:
                    # Other error - print details and try next model
                    error_text = response.text[:500] if hasattr(response, 'text') else str(response.status_code)
                    print(f"[Gemini] API error with {model}: {response.status_code} - {error_text[:200]}")
                    if model == models_to_try[-1]:  # Last model, return None
                        return None
                    continue
                    
            except requests.exceptions.Timeout:
                print(f"[Gemini] Request timeout with {model}")
                if model == models_to_try[-1]:  # Last model
                    return None
                continue
            except Exception as e:
                print(f"[Gemini] Error with {model}: {e}")
                if model == models_to_try[-1]:  # Last model
                    return None
                continue
        
        return None
            
    except Exception as e:
        print(f"[Gemini] Error calling Gemini API: {e}")
        import traceback
        traceback.print_exc()
        return None

def log_audit_event(conn, entity_type, entity_id, action, user_name=None, old_value=None, new_value=None, change_summary=None):
    """Log an audit event to the audit_log table"""
    try:
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO audit_log (entity_type, entity_id, action, user_name, old_value, new_value, change_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (entity_type, entity_id, action, user_name, old_value, new_value, change_summary))
        conn.commit()
    except Exception as e:
        print(f"[Audit] Error logging audit event: {e}")
        # Don't fail the main operation if audit logging fails

def save_element_version(conn, element_id, user_name=None):
    """Save a version snapshot of an element"""
    try:
        cur = conn.cursor()
        # Get current element
        cur.execute('SELECT * FROM domainmodel WHERE id = ?', (element_id,))
        element = cur.fetchone()
        if not element:
            return
        
        # Get current max version
        cur.execute('SELECT MAX(version_number) FROM element_versions WHERE element_id = ?', (element_id,))
        max_version = cur.fetchone()[0]
        next_version = (max_version or 0) + 1
        
        # Save version
        columns = [desc[0] for desc in cur.description]
        element_dict = dict(zip(columns, element))
        
        cur.execute('''
            INSERT INTO element_versions (element_id, version_number, name, description, enterprise, facet, element, image_url, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            element_id,
            next_version,
            element_dict.get('name'),
            element_dict.get('description'),
            element_dict.get('enterprise'),
            element_dict.get('facet'),
            element_dict.get('element'),
            element_dict.get('image_url'),
            user_name
        ))
        conn.commit()
    except Exception as e:
        print(f"[Audit] Error saving element version: {e}")

@app.route('/')
def index():
    """Serve the main HTML file"""
    return send_from_directory('.', 'index.html')

@app.route('/.well-known/appspecific/com.chrome.devtools.json')
def chrome_devtools_config():
    """Handle Chrome DevTools configuration request - return empty response to suppress 404"""
    return '', 204  # No Content

@app.route('/images/<path:filename>')
def serve_image(filename):
    """Serve images from public/images directory"""
    return send_from_directory('public/images', filename)

@app.route('/api/auth/register', methods=['POST'])
def register_user():
    """Register a new CE user"""
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    full_name = data.get('full_name')

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    conn = get_auth_connection()
    if not conn:
        return jsonify({'error': 'Auth database connection failed'}), 500

    try:
        cur = conn.cursor()
        cur.execute('SELECT id FROM users WHERE email = ?', (email,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'error': 'User already exists'}), 409

        user_id = str(uuid.uuid4())
        password_hash = hash_password(password)
        cur.execute('''
            INSERT INTO users (id, email, password_hash, full_name, is_active)
            VALUES (?, ?, ?, ?, 1)
        ''', (user_id, email, password_hash, full_name))

        token = create_session(conn, user_id)
        conn.commit()
        cur.close()
        conn.close()

        ensure_user_database(user_id)

        return jsonify({
            'token': token,
            'user': {
                'id': user_id,
                'email': email,
                'full_name': full_name
            },
            'limits': {
                'max_models': CE_MAX_MODELS,
                'max_element_occurrences': CE_MAX_ELEMENT_OCCURRENCES
            }
        }), 201
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login_user():
    """Login a CE user"""
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    conn = get_auth_connection()
    if not conn:
        return jsonify({'error': 'Auth database connection failed'}), 500

    try:
        cur = conn.cursor()
        cur.execute('SELECT id, password_hash, full_name, is_active FROM users WHERE email = ?', (email,))
        user = cur.fetchone()
        if not user or not verify_password(password, user['password_hash']):
            cur.close()
            conn.close()
            return jsonify({'error': 'Invalid credentials'}), 401
        if not user['is_active']:
            cur.close()
            conn.close()
            return jsonify({'error': 'Account is inactive'}), 403

        token = create_session(conn, user['id'])
        cur.execute('UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?', (user['id'],))
        conn.commit()
        cur.close()
        conn.close()

        ensure_user_database(user['id'])

        return jsonify({
            'token': token,
            'user': {
                'id': user['id'],
                'email': email,
                'full_name': user['full_name']
            },
            'limits': {
                'max_models': CE_MAX_MODELS,
                'max_element_occurrences': CE_MAX_ELEMENT_OCCURRENCES
            }
        }), 200
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/me', methods=['GET'])
def get_current_user():
    """Return current authenticated user info"""
    return jsonify({
        'id': g.current_user_id,
        'email': g.current_user_email,
        'full_name': g.current_user_full_name,
        'limits': {
            'max_models': CE_MAX_MODELS,
            'max_element_occurrences': CE_MAX_ELEMENT_OCCURRENCES
        }
    }), 200

@app.route('/api/records', methods=['GET'])
def get_records():
    """Get all records"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('SELECT * FROM domainmodel ORDER BY id DESC')
        columns = [desc[0] for desc in cur.description]
        records = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify(records)
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500


@app.route('/api/canvas/element-instances/search', methods=['GET'])
def search_element_instances():
    """Search element instances across all models by name or element type."""
    conn = None
    try:
        search_term = request.args.get('q', '').strip()
        if not search_term:
            return jsonify([]), 200
        
        conn = get_db_connection()
        cur = conn.cursor()
        term_like = f"%{search_term.lower()}%"
        
        cur.execute('''
            SELECT 
                cei.id,
                cei.canvas_model_id,
                cei.element_type_id,
                cei.instance_name,
                cei.description,
                cei.x_position,
                cei.y_position,
                cei.width,
                cei.height,
                cei.z_index,
                cei.created_at,
                cei.updated_at,
                dm.element as element_type,
                dm.image_url as element_image_url,
                cm.name as model_name
            FROM canvas_element_instances cei
            JOIN domainmodel dm ON cei.element_type_id = dm.id
            LEFT JOIN canvas_models cm ON cei.canvas_model_id = cm.id
            WHERE LOWER(COALESCE(cei.instance_name, '')) LIKE ?
               OR LOWER(COALESCE(dm.element, '')) LIKE ?
               OR LOWER(COALESCE(cei.description, '')) LIKE ?
            ORDER BY cei.updated_at DESC, cei.instance_name
            LIMIT 200
        ''', (term_like, term_like, term_like))
        
        columns = [desc[0] for desc in cur.description]
        instances = []
        for row in cur.fetchall():
            instance = dict(zip(columns, row))
            # Get properties for this instance
            cur.execute('''
                SELECT 
                    cpi.id,
                    cpi.property_id,
                    cpi.instance_name,
                    cpi.source,
                    cpi.rule_id,
                    dep.propertyname,
                    dep.ragtype,
                    dep.image_url,
                    dep.description
                FROM canvas_property_instances cpi
                JOIN domainelementproperties dep ON cpi.property_id = dep.id
                WHERE cpi.element_instance_id = ?
            ''', (instance['id'],))
            
            prop_columns = [desc[0] for desc in cur.description]
            properties = []
            for prop_row in cur.fetchall():
                prop = dict(zip(prop_columns, prop_row))
                properties.append({
                    'id': prop['id'],
                    'property_id': prop['property_id'],
                    'instance_name': prop['instance_name'],
                    'source': prop['source'],
                    'rule_id': prop['rule_id'],
                    'propertyname': prop['propertyname'],
                    'ragtype': prop['ragtype'],
                    'image_url': prop['image_url'],
                    'description': prop['description']
                })
            
            instance['properties'] = properties
            
            # Get relationships for this instance (as source)
            cur.execute('''
                SELECT 
                    cr.id,
                    cr.target_instance_id,
                    cr.relationship_type,
                    cei.instance_name as target_instance_name,
                    cei.element_type_id as target_element_type_id,
                    dm.element as target_element_type
                FROM canvas_relationships cr
                JOIN canvas_element_instances cei ON cr.target_instance_id = cei.id
                JOIN domainmodel dm ON cei.element_type_id = dm.id
                WHERE cr.source_instance_id = ?
            ''', (instance['id'],))
            
            rel_columns = [desc[0] for desc in cur.description]
            relationships = []
            for rel_row in cur.fetchall():
                rel = dict(zip(rel_columns, rel_row))
                relationships.append({
                    'id': rel['id'],
                    'target_instance_id': rel['target_instance_id'],
                    'relationship_type': rel['relationship_type'],
                    'target_instance_name': rel['target_instance_name'],
                    'target_element_type_id': rel['target_element_type_id'],
                    'target_element_type': rel['target_element_type']
                })
            
            instance['relationships'] = relationships
            
            # Get incoming relationships for this instance (as target)
            cur.execute('''
                SELECT 
                    cr.id,
                    cr.source_instance_id,
                    cr.relationship_type,
                    cei.instance_name as source_instance_name,
                    cei.element_type_id as source_element_type_id,
                    dm.element as source_element_type
                FROM canvas_relationships cr
                JOIN canvas_element_instances cei ON cr.source_instance_id = cei.id
                JOIN domainmodel dm ON cei.element_type_id = dm.id
                WHERE cr.target_instance_id = ?
            ''', (instance['id'],))
            
            inc_columns = [desc[0] for desc in cur.description]
            incoming_relationships = []
            for inc_row in cur.fetchall():
                inc = dict(zip(inc_columns, inc_row))
                incoming_relationships.append({
                    'id': inc['id'],
                    'source_instance_id': inc['source_instance_id'],
                    'relationship_type': inc['relationship_type'],
                    'source_instance_name': inc['source_instance_name'],
                    'source_element_type_id': inc['source_element_type_id'],
                    'source_element_type': inc['source_element_type']
                })
            
            instance['incoming_relationships'] = incoming_relationships
            instance['image_url'] = instance['element_image_url']
            instances.append(instance)
        
        cur.close()
        conn.close()
        
        return jsonify(instances)
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/records/<int:record_id>', methods=['GET'])
def get_record(record_id):
    """Get a single record by ID"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('SELECT * FROM domainmodel WHERE id = ?', (record_id,))
        row = cur.fetchone()
        
        if not row:
            cur.close()
            conn.close()
            return jsonify({'error': 'Record not found'}), 404
        
        columns = [desc[0] for desc in cur.description]
        record = dict(zip(columns, row))
        cur.close()
        conn.close()
        return jsonify(record)
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/records/bulk', methods=['POST'])
def bulk_add_records():
    """Bulk import records from JSON array"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.json
        records = data.get('records', [])
        
        if not records:
            return jsonify({'error': 'No records provided'}), 400
        
        image_mapping = {
            'people': '/images/people-element.svg',
            'activity': '/images/activity-element.svg',
            'outcome': '/images/outcome-element.svg',
            'object': '/images/object-element.svg',
            'capability': '/images/small-shape-capability.svg',
            'asset': '/images/small-shape-asset.svg',
            'process': '/images/small-shape-process.svg',
            'purpose': '/images/purpose.png',
            'content': '/images/content.png',
            'story': '/images/story.png',
            'channel': '/images/channel.png',
            'journey': '/images/journey.png',
            'task': '/images/task.png',
            'product': '/images/shape-product.svg',
            'organisation': '/images/small-shape-organisation.svg',
            'organization': '/images/small-shape-organisation.svg',
            'brand': '/images/shape-brand.svg'
        }
        
        cur = conn.cursor()
        created_records = []
        errors = []
        
        for idx, record in enumerate(records):
            try:
                element_type = (record.get('element') or '').lower().strip()
                image_url = image_mapping.get(element_type)
                
                cur.execute(
                    '''INSERT INTO domainmodel (name, description, enterprise, facet, element, image_url, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                    (record.get('name'), record.get('description'), record.get('enterprise'), 
                     record.get('facet'), record.get('element'), image_url)
                )
                element_id = cur.lastrowid
                created_records.append(element_id)
            except Exception as e:
                errors.append(f"Row {idx + 1}: {str(e)}")
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'created': len(created_records),
            'errors': errors,
            'record_ids': created_records
        })
    except Exception as e:
        if conn:
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/records', methods=['POST'])
def add_record():
    """Add a new record"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.json
        element_type = (data.get('element') or data.get('name') or '').lower()
        
        # Map element type to appropriate image URL
        image_mapping = {
            'people': '/images/people-element.svg',
            'activity': '/images/activity-element.svg',
            'outcome': '/images/outcome-element.svg',
            'object': '/images/object-element.svg',
            'capability': '/images/small-shape-capability.svg',
            'asset': '/images/small-shape-asset.svg',
            'process': '/images/small-shape-process.svg',
            'purpose': '/images/purpose.png',
            'content': '/images/content.png',
            'story': '/images/story.png',
            'channel': '/images/channel.png',
            'journey': '/images/journey.png',
            'task': '/images/task.png',
            'product': '/images/shape-product.svg',
            'organisation': '/images/small-shape-organisation.svg',
            'organization': '/images/small-shape-organisation.svg',
            'brand': '/images/shape-brand.svg'
        }
        
        # Determine image URL based on element type
        image_url = image_mapping.get(element_type)
        # If no mapping found, use None (will be NULL in database)
        
        cur = conn.cursor()
        cur.execute(
            '''INSERT INTO domainmodel (name, description, enterprise, facet, element, image_url, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
            (data.get('name'), data.get('description'), data.get('enterprise'), 
             data.get('facet'), data.get('element'), image_url)
        )
        conn.commit()
        element_id = cur.lastrowid
        
        # Get user name from request
        user_name = data.get('user_name') or request.headers.get('X-User-Name') or 'System'
        
        # Log audit event
        log_audit_event(conn, 'element', element_id, 'CREATE', user_name, None, 
                       f"Created element: {data.get('name')}", 
                       f"Created new {data.get('element')} element")
        
        # Save initial version
        save_element_version(conn, element_id, user_name)
        
        cur.execute('SELECT * FROM domainmodel WHERE id = ?', (element_id,))
        columns = [desc[0] for desc in cur.description]
        record = dict(zip(columns, cur.fetchone()))
        
        # Add selected properties if provided
        selected_properties = data.get('selected_properties', [])
        if selected_properties:
            for prop_data in selected_properties:
                ragtype = prop_data.get('ragtype')
                image_url = prop_data.get('image_url')
                
                # Automatically set image URL based on RAG type if not provided
                if not image_url and ragtype:
                    ragtype_lower = str(ragtype).lower().strip()
                    # Check for new values first (Negative, Warning, Positive)
                    if ragtype_lower == 'negative' or ragtype_lower.startswith('negative'):
                        image_url = '/images/Tag-Red.svg'
                    elif ragtype_lower == 'warning' or ragtype_lower.startswith('warning'):
                        image_url = '/images/Tag-Yellow.svg'
                    elif ragtype_lower == 'positive' or ragtype_lower.startswith('positive'):
                        image_url = '/images/Tag-Green.svg'
                    # Backward compatibility with old values
                    elif ragtype_lower == 'red' or ragtype_lower.startswith('red'):
                        image_url = '/images/Tag-Red.svg'
                    elif ragtype_lower == 'amber' or ragtype_lower == 'yellow' or ragtype_lower.startswith('amber') or ragtype_lower.startswith('yellow'):
                        image_url = '/images/Tag-Yellow.svg'
                    elif ragtype_lower == 'green' or ragtype_lower.startswith('green'):
                        image_url = '/images/Tag-Green.svg'
                    elif ragtype_lower == 'black' or ragtype_lower.startswith('black'):
                        image_url = '/images/Tag-Black.svg'
                
                cur.execute('''
                    INSERT INTO domainelementproperties (element_id, ragtype, propertyname, description, image_url, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ''', (
                    element_id,
                    ragtype,
                    prop_data.get('propertyname'),
                    prop_data.get('description'),
                    image_url
                ))
        
        conn.commit()
        cur.close()
        conn.close()
        return jsonify(record), 201
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/records/export', methods=['GET'])
def export_records():
    """Export records in various formats"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        format_type = request.args.get('format', 'json').lower()
        enterprise_filter = request.args.get('enterprise', None)
        
        cur = conn.cursor()
        
        if enterprise_filter:
            cur.execute('''
                SELECT id, name, description, enterprise, facet, element, image_url, created_at, updated_at
                FROM domainmodel
                WHERE enterprise = ?
                ORDER BY id
            ''', (enterprise_filter,))
        else:
            cur.execute('''
                SELECT id, name, description, enterprise, facet, element, image_url, created_at, updated_at
                FROM domainmodel
                ORDER BY id
            ''')
        
        columns = [desc[0] for desc in cur.description]
        records = [dict(zip(columns, row)) for row in cur.fetchall()]
        
        cur.close()
        conn.close()
        
        if format_type == 'csv':
            # Generate CSV
            import csv
            import io
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=['name', 'element', 'facet', 'enterprise', 'description'])
            writer.writeheader()
            for record in records:
                writer.writerow({
                    'name': record.get('name', ''),
                    'element': record.get('element', ''),
                    'facet': record.get('facet', ''),
                    'enterprise': record.get('enterprise', ''),
                    'description': record.get('description', '')
                })
            csv_data = output.getvalue()
            output.close()
            
            from flask import Response
            return Response(
                csv_data,
                mimetype='text/csv',
                headers={'Content-Disposition': 'attachment; filename=elements_export.csv'}
            )
        else:
            # Default: JSON
            return jsonify(records)
    except Exception as e:
        if conn:
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/integrations/webhook', methods=['POST'])
def webhook_integration():
    """Webhook endpoint for external integrations"""
    try:
        data = request.json
        event_type = data.get('event_type')
        payload = data.get('payload', {})
        
        # Log webhook event
        print(f"[Webhook] Received {event_type} event")
        
        # Process different event types
        if event_type == 'element.created':
            # External system created an element
            return jsonify({'status': 'received', 'message': 'Element creation webhook processed'}), 200
        elif event_type == 'element.updated':
            return jsonify({'status': 'received', 'message': 'Element update webhook processed'}), 200
        elif event_type == 'relationship.created':
            return jsonify({'status': 'received', 'message': 'Relationship creation webhook processed'}), 200
        else:
            return jsonify({'status': 'received', 'message': f'Webhook event {event_type} received'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reports/generate', methods=['POST'])
def generate_report():
    """Generate a custom report"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.json
        report_type = data.get('type', 'summary')
        enterprise_filter = data.get('enterprise')
        format_type = data.get('format', 'html')
        
        cur = conn.cursor()
        
        # Get elements
        if enterprise_filter:
            cur.execute('SELECT * FROM domainmodel WHERE enterprise = ?', (enterprise_filter,))
        else:
            cur.execute('SELECT * FROM domainmodel')
        elements = cur.fetchall()
        element_columns = [desc[0] for desc in cur.description]
        elements_list = [dict(zip(element_columns, row)) for row in elements]
        
        # Get relationships
        if enterprise_filter:
            cur.execute('''
                SELECT r.*, s.name as source_name, t.name as target_name
                FROM domainmodelrelationship r
                JOIN domainmodel s ON r.source_element_id = s.id
                JOIN domainmodel t ON r.target_element_id = t.id
                WHERE s.enterprise = ? AND t.enterprise = ?
            ''', (enterprise_filter, enterprise_filter))
        else:
            cur.execute('''
                SELECT r.*, s.name as source_name, t.name as target_name
                FROM domainmodelrelationship r
                JOIN domainmodel s ON r.source_element_id = s.id
                JOIN domainmodel t ON r.target_element_id = t.id
            ''')
        rel_columns = [desc[0] for desc in cur.description]
        relationships = [dict(zip(rel_columns, row)) for row in cur.fetchall()]
        
        cur.close()
        conn.close()
        
        # Generate report based on type
        if report_type == 'summary':
            report_html = f"""
            <html>
            <head><title>Repository Summary Report</title></head>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h1>Repository Summary Report</h1>
                <h2>Overview</h2>
                <p>Total Elements: {len(elements_list)}</p>
                <p>Total Relationships: {len(relationships)}</p>
                {f'<p>Enterprise: {enterprise_filter}</p>' if enterprise_filter else ''}
                
                <h2>Elements by Type</h2>
                <ul>
            """
            element_types = {}
            for e in elements_list:
                elem_type = e.get('element') or 'Unknown'
                element_types[elem_type] = element_types.get(elem_type, 0) + 1
            
            for elem_type, count in sorted(element_types.items()):
                report_html += f"<li>{elem_type}: {count}</li>"
            
            report_html += """
                </ul>
                <h2>Recent Elements</h2>
                <ul>
            """
            for e in elements_list[:10]:
                report_html += f"<li>{e.get('name', 'Unnamed')} ({e.get('element', 'Unknown')})</li>"
            
            report_html += """
                </ul>
            </body>
            </html>
            """
            
            if format_type == 'pdf':
                # For PDF, return HTML that can be converted
                return jsonify({'html': report_html, 'format': 'html'})
            else:
                from flask import Response
                return Response(report_html, mimetype='text/html',
                              headers={'Content-Disposition': 'attachment; filename=repository_report.html'})
        
        return jsonify({'error': 'Unknown report type'}), 400
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/openapi', methods=['GET'])
def export_openapi_spec():
    """Export OpenAPI/Swagger specification for API"""
    spec = {
        'openapi': '3.0.0',
        'info': {
            'title': 'AskED+ API',
            'version': '1.0.0',
            'description': 'API for Enterprise Design Modeling and Repository Analysis'
        },
        'paths': {
            '/api/records': {
                'get': {'summary': 'Get all elements', 'responses': {'200': {'description': 'List of elements'}}},
                'post': {'summary': 'Create element', 'responses': {'201': {'description': 'Element created'}}}
            },
            '/api/relationships': {
                'get': {'summary': 'Get all relationships', 'responses': {'200': {'description': 'List of relationships'}}},
                'post': {'summary': 'Create relationship', 'responses': {'201': {'description': 'Relationship created'}}}
            },
            '/api/analytics': {
                'get': {'summary': 'Get repository analytics', 'responses': {'200': {'description': 'Analytics data'}}}
            }
        }
    }
    return jsonify(spec)


@app.route('/api/insights/recommendations', methods=['GET'])
def get_ai_recommendations():
    """Get AI-powered recommendations for repository improvements"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        enterprise_filter = request.args.get('enterprise')
        cur = conn.cursor()
        
        # Get all elements
        if enterprise_filter:
            cur.execute('SELECT * FROM domainmodel WHERE enterprise = ?', (enterprise_filter,))
        else:
            cur.execute('SELECT * FROM domainmodel')
        elements = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        elements_list = [dict(zip(columns, row)) for row in elements]
        
        # Get all relationships
        if enterprise_filter:
            cur.execute('''
                SELECT r.*, s.name as source_name, t.name as target_name, s.enterprise as source_enterprise, t.enterprise as target_enterprise
                FROM domainmodelrelationship r
                JOIN domainmodel s ON r.source_element_id = s.id
                JOIN domainmodel t ON r.target_element_id = t.id
                WHERE s.enterprise = ? AND t.enterprise = ?
            ''', (enterprise_filter, enterprise_filter))
        else:
            cur.execute('''
                SELECT r.*, s.name as source_name, t.name as target_name, s.enterprise as source_enterprise, t.enterprise as target_enterprise
                FROM domainmodelrelationship r
                JOIN domainmodel s ON r.source_element_id = s.id
                JOIN domainmodel t ON r.target_element_id = t.id
            ''')
        rel_columns = [desc[0] for desc in cur.description]
        relationships = [dict(zip(rel_columns, row)) for row in cur.fetchall()]
        
        # Get properties
        cur.execute('SELECT element_id FROM domainelementproperties')
        elements_with_properties = set(row[0] for row in cur.fetchall())
        
        recommendations = []
        
        # Recommendation 1: Orphaned elements
        element_ids_with_rels = set(r['source_element_id'] for r in relationships) | set(r['target_element_id'] for r in relationships)
        orphaned = [e for e in elements_list if e['id'] not in element_ids_with_rels]
        if orphaned:
            recommendations.append({
                'type': 'orphaned_elements',
                'priority': 'high',
                'title': 'Orphaned Elements Detected',
                'description': f'{len(orphaned)} elements have no relationships. Consider connecting them to other elements.',
                'count': len(orphaned),
                'elements': orphaned[:5],
                'action': 'Add relationships to connect these elements'
            })
        
        # Recommendation 2: Missing descriptions
        missing_descriptions = [e for e in elements_list if not e.get('description') or not e['description'].strip()]
        if missing_descriptions:
            recommendations.append({
                'type': 'missing_descriptions',
                'priority': 'medium',
                'title': 'Elements Missing Descriptions',
                'description': f'{len(missing_descriptions)} elements lack descriptions. Adding descriptions improves repository quality.',
                'count': len(missing_descriptions),
                'elements': missing_descriptions[:5],
                'action': 'Add descriptions to improve documentation'
            })
        
        # Recommendation 3: Missing properties
        missing_properties = [e for e in elements_list if e['id'] not in elements_with_properties]
        if missing_properties:
            recommendations.append({
                'type': 'missing_properties',
                'priority': 'medium',
                'title': 'Elements Without Properties',
                'description': f'{len(missing_properties)} elements have no properties. Properties help track status, risks, and metrics.',
                'count': len(missing_properties),
                'elements': missing_properties[:5],
                'action': 'Add properties to track element status'
            })
        
        # Recommendation 4: EDGY pattern suggestions
        capabilities = [e for e in elements_list if e.get('element', '').lower() == 'capability']
        assets = [e for e in elements_list if e.get('element', '').lower() == 'asset']
        processes = [e for e in elements_list if e.get('element', '').lower() == 'process']
        
        if capabilities and not assets:
            recommendations.append({
                'type': 'pattern_suggestion',
                'priority': 'low',
                'title': 'EDGY Pattern Suggestion',
                'description': 'You have Capabilities but no Assets. In EDGY Architecture patterns, Capabilities typically require Assets.',
                'count': len(capabilities),
                'action': 'Consider adding Assets that support your Capabilities'
            })
        
        if capabilities and not processes:
            recommendations.append({
                'type': 'pattern_suggestion',
                'priority': 'low',
                'title': 'EDGY Pattern Suggestion',
                'description': 'You have Capabilities but no Processes. Processes realise Capabilities in EDGY patterns.',
                'count': len(capabilities),
                'action': 'Consider adding Processes that realise your Capabilities'
            })
        
        # Recommendation 5: Incomplete relationships
        relationships_without_desc = [r for r in relationships if not r.get('description') or not r['description'].strip()]
        if relationships_without_desc:
            recommendations.append({
                'type': 'incomplete_relationships',
                'priority': 'low',
                'title': 'Relationships Missing Descriptions',
                'description': f'{len(relationships_without_desc)} relationships lack descriptions.',
                'count': len(relationships_without_desc),
                'action': 'Add descriptions to clarify relationship purpose'
            })
        
        # Recommendation 6: Facet coverage
        facet_counts = {}
        for e in elements_list:
            facet = e.get('facet') or 'Base'
            facet_counts[facet] = facet_counts.get(facet, 0) + 1
        
        if len(facet_counts) == 1 and 'Base' in facet_counts:
            recommendations.append({
                'type': 'facet_coverage',
                'priority': 'medium',
                'title': 'Limited Facet Coverage',
                'description': 'All elements are in the Base facet. Consider using Architecture, Identity, Experience, Product, Organisation, or Brand facets for better organization.',
                'action': 'Explore EDGY facets to organize your elements'
            })
        
        cur.close()
        conn.close()
        
        return jsonify({
            'recommendations': recommendations,
            'total': len(recommendations),
            'enterprise': enterprise_filter
        })
    except Exception as e:
        if conn:
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/repositories/compare', methods=['GET'])
def compare_repositories():
    """Compare two enterprise repositories"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        enterprise1 = request.args.get('enterprise1')
        enterprise2 = request.args.get('enterprise2')
        
        if not enterprise1 or not enterprise2:
            return jsonify({'error': 'Both enterprises must be specified'}), 400
        
        cur = conn.cursor()
        
        # Get elements for each enterprise
        cur.execute('SELECT * FROM domainmodel WHERE enterprise = ?', (enterprise1,))
        columns = [desc[0] for desc in cur.description]
        elements1 = [dict(zip(columns, row)) for row in cur.fetchall()]
        
        cur.execute('SELECT * FROM domainmodel WHERE enterprise = ?', (enterprise2,))
        elements2 = [dict(zip(columns, row)) for row in cur.fetchall()]
        
        # Get relationships for each enterprise
        cur.execute('''
            SELECT r.*, s.name as source_name, t.name as target_name
            FROM domainmodelrelationship r
            JOIN domainmodel s ON r.source_element_id = s.id
            JOIN domainmodel t ON r.target_element_id = t.id
            WHERE s.enterprise = ? AND t.enterprise = ?
        ''', (enterprise1, enterprise1))
        rel_columns = [desc[0] for desc in cur.description]
        relationships1 = [dict(zip(rel_columns, row)) for row in cur.fetchall()]
        
        cur.execute('''
            SELECT r.*, s.name as source_name, t.name as target_name
            FROM domainmodelrelationship r
            JOIN domainmodel s ON r.source_element_id = s.id
            JOIN domainmodel t ON r.target_element_id = t.id
            WHERE s.enterprise = ? AND t.enterprise = ?
        ''', (enterprise2, enterprise2))
        relationships2 = [dict(zip(rel_columns, row)) for row in cur.fetchall()]
        
        # Compare elements
        elements1_names = {e['name']: e for e in elements1}
        elements2_names = {e['name']: e for e in elements2}
        
        common_elements = []
        unique_to_1 = []
        unique_to_2 = []
        different_elements = []
        
        for name, elem1 in elements1_names.items():
            if name in elements2_names:
                elem2 = elements2_names[name]
                # Check if they're different
                if (elem1.get('description') != elem2.get('description') or
                    elem1.get('facet') != elem2.get('facet') or
                    elem1.get('element') != elem2.get('element')):
                    different_elements.append({
                        'name': name,
                        'enterprise1': elem1,
                        'enterprise2': elem2
                    })
                else:
                    common_elements.append(elem1)
            else:
                unique_to_1.append(elem1)
        
        for name, elem2 in elements2_names.items():
            if name not in elements1_names:
                unique_to_2.append(elem2)
        
        # Compare relationships
        rel1_signatures = {(r['source_name'], r['target_name'], r['relationship_type']): r for r in relationships1}
        rel2_signatures = {(r['source_name'], r['target_name'], r['relationship_type']): r for r in relationships2}
        
        common_relationships = []
        unique_rel_to_1 = []
        unique_rel_to_2 = []
        
        for sig, rel1 in rel1_signatures.items():
            if sig in rel2_signatures:
                common_relationships.append(rel1)
            else:
                unique_rel_to_1.append(rel1)
        
        for sig, rel2 in rel2_signatures.items():
            if sig not in rel1_signatures:
                unique_rel_to_2.append(rel2)
        
        cur.close()
        conn.close()
        
        return jsonify({
            'enterprise1': enterprise1,
            'enterprise2': enterprise2,
            'summary': {
                'elements1_count': len(elements1),
                'elements2_count': len(elements2),
                'common_elements_count': len(common_elements),
                'unique_to_1_count': len(unique_to_1),
                'unique_to_2_count': len(unique_to_2),
                'different_elements_count': len(different_elements),
                'relationships1_count': len(relationships1),
                'relationships2_count': len(relationships2),
                'common_relationships_count': len(common_relationships),
                'unique_rel_to_1_count': len(unique_rel_to_1),
                'unique_rel_to_2_count': len(unique_rel_to_2)
            },
            'elements': {
                'common': common_elements,
                'unique_to_1': unique_to_1,
                'unique_to_2': unique_to_2,
                'different': different_elements
            },
            'relationships': {
                'common': common_relationships,
                'unique_to_1': unique_rel_to_1,
                'unique_to_2': unique_rel_to_2
            }
        })
    except Exception as e:
        if conn:
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/records/<int:record_id>', methods=['DELETE'])
def delete_record(record_id):
    """Delete a record and all related foreign key references"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        user_name = request.headers.get('X-User-Name') or 'System'
        
        # Fetch the full record BEFORE deletion (for returning in response)
        cur = conn.cursor()
        cur.execute('SELECT * FROM domainmodel WHERE id = ?', (record_id,))
        record_to_delete = cur.fetchone()
        
        # Check if record exists
        if not record_to_delete:
            cur.close()
            conn.close()
            return jsonify({'error': 'Record not found'}), 404
        
        # Get element name for audit log
        cur.execute('SELECT name FROM domainmodel WHERE id = ?', (record_id,))
        name_result = cur.fetchone()
        element_name = name_result[0] if name_result else 'Unknown'
        
        # Temporarily disable foreign key constraints to allow deletion
        # This is safe because we're manually deleting all related records first
        # PRAGMA must be executed on the connection, not cursor
        conn.execute('PRAGMA foreign_keys = OFF')
        
        # Delete all related records first to avoid foreign key constraint violations
        relationships_deleted_as_source = 0
        relationships_deleted_as_target = 0
        properties_deleted = 0
        diagram_elements_deleted = 0
        history_deleted = 0
        
        # 1. Delete relationships where this element is the source
        try:
            cur.execute('DELETE FROM domainmodelrelationship WHERE source_element_id = ?', (record_id,))
            relationships_deleted_as_source = cur.rowcount
        except Exception as e:
            print(f"Warning: Could not delete relationships as source: {e}")
            import traceback
            traceback.print_exc()
        
        # 2. Delete relationships where this element is the target
        try:
            cur.execute('DELETE FROM domainmodelrelationship WHERE target_element_id = ?', (record_id,))
            relationships_deleted_as_target = cur.rowcount
        except Exception as e:
            print(f"Warning: Could not delete relationships as target: {e}")
            import traceback
            traceback.print_exc()
        
        # 3. Delete element properties
        try:
            cur.execute('DELETE FROM domainelementproperties WHERE element_id = ?', (record_id,))
            properties_deleted = cur.rowcount
        except Exception as e:
            print(f"Warning: Could not delete properties: {e}")
            import traceback
            traceback.print_exc()
        
        # 5. Delete element version history records
        try:
            cur.execute('DELETE FROM element_versions WHERE element_id = ?', (record_id,))
            history_deleted = cur.rowcount
        except Exception as e:
            print(f"Warning: Could not delete element versions: {e}")
            import traceback
            traceback.print_exc()
        
        # Now delete the element itself
        cur.execute('DELETE FROM domainmodel WHERE id = ?', (record_id,))
        element_deleted = cur.rowcount
        
        # Re-enable foreign key constraints
        conn.execute('PRAGMA foreign_keys = ON')
        
        if element_deleted == 0:
            cur.close()
            conn.close()
            return jsonify({'error': 'Record not found'}), 404
        
        conn.commit()
        
        # Log audit event (don't fail if this doesn't work)
        try:
            log_audit_event(conn, 'element', record_id, 'DELETE', user_name, 
                           f"Element: {element_name}", None, 
                           f"Deleted element: {element_name} (and {relationships_deleted_as_source + relationships_deleted_as_target} relationships, {properties_deleted} properties)")
        except Exception as audit_error:
            print(f"Warning: Could not log audit event: {audit_error}")
        
        cur.close()
        conn.close()
        return jsonify({
            'message': 'Record deleted successfully', 
            'deleted_related': {
                'relationships_as_source': relationships_deleted_as_source,
                'relationships_as_target': relationships_deleted_as_target,
                'properties': properties_deleted,
                'diagram_elements': diagram_elements_deleted,
                'history_records': history_deleted
            }
        })
    except Exception as e:
        if conn:
            try:
                conn.rollback()
                conn.execute('PRAGMA foreign_keys = ON')  # Re-enable if disabled
            except:
                pass
            try:
                if cur:
                    cur.close()
            except:
                pass
            conn.close()
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error deleting record {record_id}: {error_trace}")
        return jsonify({'error': str(e), 'details': error_trace}), 500

# Relationship endpoints
@app.route('/api/analytics', methods=['GET'])
def get_analytics():
    """Get comprehensive analytics and metrics for the repository based on Element Instances"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Get all element instances with their element type information
        cur.execute('''
            SELECT 
                cei.id,
                cei.instance_name,
                cei.element_type_id,
                dm.name AS element_type_name,
                dm.element AS element_type,
                dm.facet,
                dm.enterprise,
                dm.description AS element_type_description,
                dm.image_url,
                cei.created_at
            FROM canvas_element_instances cei
            JOIN domainmodel dm ON cei.element_type_id = dm.id
        ''')
        element_instances = cur.fetchall()
        
        # Get all canvas relationships (relationships between instances)
        cur.execute('''
            SELECT id, source_instance_id, target_instance_id, relationship_type, created_at
            FROM canvas_relationships
        ''')
        instance_relationships = cur.fetchall()
        
        # Get all properties for element types (properties are assigned to element types, not instances)
        # But we'll count them per instance based on the instance's element_type_id
        cur.execute('''
            SELECT element_id, ragtype, propertyname, description
            FROM domainelementproperties
        ''')
        properties = cur.fetchall()
        
        # Create a map of element_type_id to properties
        properties_by_type = {}
        for prop in properties:
            elem_type_id = prop[0]
            if elem_type_id not in properties_by_type:
                properties_by_type[elem_type_id] = []
            properties_by_type[elem_type_id].append(prop)
        
        # Get all enterprises from element instances
        cur.execute('SELECT DISTINCT dm.enterprise FROM canvas_element_instances cei JOIN domainmodel dm ON cei.element_type_id = dm.id WHERE dm.enterprise IS NOT NULL')
        enterprises = [row[0] for row in cur.fetchall()]
        
        # Calculate metrics based on element instances
        total_elements = len(element_instances)
        total_relationships = len(instance_relationships)
        total_properties = sum(len(props) for props in properties_by_type.values())
        total_enterprises = len(enterprises)
        
        # Completeness metrics for instances
        instances_with_description = sum(1 for e in element_instances if e[7] and e[7].strip())
        instances_with_properties = sum(1 for e in element_instances if e[2] in properties_by_type)
        instance_ids_with_rels = set(r[1] for r in instance_relationships) | set(r[2] for r in instance_relationships)
        instances_with_relationships = sum(1 for e in element_instances if e[0] in instance_ids_with_rels)
        instances_with_images = sum(1 for e in element_instances if e[8] and e[8].strip())
        
        completeness_score = 0
        if total_elements > 0:
            completeness_score = (
                (instances_with_description / total_elements * 0.3) +
                (instances_with_properties / total_elements * 0.3) +
                (instances_with_relationships / total_elements * 0.3) +
                (instances_with_images / total_elements * 0.1)
            ) * 100
        
        # Relationship density
        avg_relationships_per_element = total_relationships / total_elements if total_elements > 0 else 0
        
        # Facet distribution based on instances
        facet_counts = {}
        for instance in element_instances:
            facet = instance[5] or 'Base'
            facet_counts[facet] = facet_counts.get(facet, 0) + 1
        
        # Element type distribution based on instances
        element_type_counts = {}
        for instance in element_instances:
            elem_type = instance[4] or 'Unknown'
            element_type_counts[elem_type] = element_type_counts.get(elem_type, 0) + 1
        
        # Relationship type distribution
        relationship_type_counts = {}
        for rel in instance_relationships:
            rel_type = rel[3] or 'Unknown'
            relationship_type_counts[rel_type] = relationship_type_counts.get(rel_type, 0) + 1
        
        # Enterprise distribution based on instances
        enterprise_counts = {}
        for instance in element_instances:
            ent = instance[6] or 'Unassigned'
            enterprise_counts[ent] = enterprise_counts.get(ent, 0) + 1
        
        # Orphaned instances (no relationships)
        orphaned_instances = [e for e in element_instances if e[0] not in instance_ids_with_rels]
        
        # Incomplete instances
        incomplete_instances = []
        for instance in element_instances:
            missing = []
            if not instance[7] or not instance[7].strip():
                missing.append('description')
            if instance[2] not in properties_by_type:
                missing.append('properties')
            if instance[0] not in instance_ids_with_rels:
                missing.append('relationships')
            if not instance[8] or not instance[8].strip():
                missing.append('image')
            if missing:
                incomplete_instances.append({
                    'id': instance[0],
                    'name': instance[1],
                    'missing': missing
                })
        
        # RAG distribution - count properties assigned to element instances
        rag_counts = {'negative': 0, 'warning': 0, 'positive': 0, 'none': 0}
        for instance in element_instances:
            elem_type_id = instance[2]
            if elem_type_id in properties_by_type:
                for prop in properties_by_type[elem_type_id]:
                    rag = (prop[1] or '').lower().strip()
                    if rag == 'negative':
                        rag_counts['negative'] += 1
                    elif rag == 'warning':
                        rag_counts['warning'] += 1
                    elif rag == 'positive':
                        rag_counts['positive'] += 1
                    else:
                        rag_counts['none'] += 1
        
        # Get additional stats for the analytics modal
        cur.execute('SELECT COUNT(*) FROM domainmodel')
        total_element_types = cur.fetchone()[0]
        
        cur.execute('SELECT COUNT(*) FROM domainmodelrelationship')
        total_relationship_rules = cur.fetchone()[0]
        
        cur.execute('SELECT COUNT(DISTINCT propertyname) FROM domainelementproperties WHERE propertyname IS NOT NULL')
        total_unique_properties = cur.fetchone()[0]
        
        cur.execute('SELECT COUNT(*) FROM canvas_models')
        total_canvas_models = cur.fetchone()[0]
        
        cur.execute('SELECT COUNT(DISTINCT enterprise) FROM domainmodel WHERE enterprise IS NOT NULL')
        total_unique_enterprises = cur.fetchone()[0]
        
        # Elements by type (from element instances)
        elements_by_type = element_type_counts
        
        # Elements by facet (from element instances)
        elements_by_facet = facet_counts
        
        # Elements by enterprise (from element instances)
        elements_by_enterprise = enterprise_counts
        
        # Relationships by type (from instance relationships)
        relationships_by_type = relationship_type_counts
        
        # Top elements (most used in canvas)
        cur.execute('''
            SELECT 
                cei.instance_name,
                dm.element as element_type,
                COUNT(*) as count
            FROM canvas_element_instances cei
            JOIN domainmodel dm ON cei.element_type_id = dm.id
            GROUP BY cei.instance_name, dm.element
            ORDER BY count DESC
            LIMIT 10
        ''')
        top_elements = [{'name': row[0], 'element_type': row[1], 'count': row[2]} for row in cur.fetchall()]
        
        # Top relationships (from canvas)
        cur.execute('''
            SELECT 
                cr.relationship_type,
                COUNT(*) as count
            FROM canvas_relationships cr
            WHERE cr.relationship_type IS NOT NULL
            GROUP BY cr.relationship_type
            ORDER BY count DESC
            LIMIT 10
        ''')
        top_relationships = [{'type': row[0], 'count': row[1]} for row in cur.fetchall()]
        
        # Get design rules and violations summary
        cur.execute('SELECT COUNT(*) FROM design_rules WHERE active = 1')
        active_rules_count = cur.fetchone()[0]
        
        cur.execute('SELECT COUNT(*) FROM design_rule_violations WHERE severity = ?', ('warning',))
        warning_violations_count = cur.fetchone()[0]
        
        cur.execute('SELECT COUNT(*) FROM design_rule_violations WHERE severity = ?', ('negative',))
        negative_violations_count = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        
        return jsonify({
            'stats': {
                'total_elements': total_element_types,
                'total_relationships': total_relationship_rules,
                'total_properties': total_unique_properties,
                'total_canvas_models': total_canvas_models,
                'total_element_instances': total_elements,
                'total_enterprises': total_unique_enterprises
            },
            'elements_by_type': elements_by_type,
            'elements_by_facet': elements_by_facet,
            'elements_by_enterprise': elements_by_enterprise,
            'relationships_by_type': relationships_by_type,
            'top_elements': top_elements,
            'top_relationships': top_relationships,
            'design_rules': {
                'active_rules_count': active_rules_count,
                'warning_violations_count': warning_violations_count,
                'negative_violations_count': negative_violations_count
            },
            'summary': {
                'total_elements': total_elements,
                'total_relationships': total_relationships,
                'total_properties': total_properties,
                'total_enterprises': total_enterprises,
                'completeness_score': round(completeness_score, 1),
                'avg_relationships_per_element': round(avg_relationships_per_element, 2),
                'orphaned_elements_count': len(orphaned_instances),
                'incomplete_elements_count': len(incomplete_instances)
            },
            'distributions': {
                'facets': facet_counts,
                'element_types': element_type_counts,
                'relationship_types': relationship_type_counts,
                'enterprises': enterprise_counts,
                'rag_status': rag_counts
            },
            'health_metrics': {
                'elements_with_description': instances_with_description,
                'elements_with_properties': instances_with_properties,
                'elements_with_relationships': instances_with_relationships,
                'elements_with_images': instances_with_images,
                'description_coverage': round(instances_with_description / total_elements * 100, 1) if total_elements > 0 else 0,
                'properties_coverage': round(instances_with_properties / total_elements * 100, 1) if total_elements > 0 else 0,
                'relationships_coverage': round(instances_with_relationships / total_elements * 100, 1) if total_elements > 0 else 0,
                'images_coverage': round(instances_with_images / total_elements * 100, 1) if total_elements > 0 else 0
            },
            'issues': {
                'orphaned_elements': [{'id': e[0], 'name': e[1]} for e in orphaned_instances[:10]],
                'incomplete_elements': incomplete_instances[:10]
            }
        })
    except Exception as e:
        if conn:
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# Design Rules API Endpoints
@app.route('/api/analytics/design-rules', methods=['GET'])
def get_design_rules():
    """Get all design rules"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT id, name, description, rule_type, subject_element_type,
                   relationship_type, target_element_type, conditions_json, active,
                   created_at, updated_at
            FROM design_rules
            ORDER BY created_at DESC
        ''')
        
        rules = []
        for row in cur.fetchall():
            rules.append({
                'id': row[0],
                'name': row[1],
                'description': row[2],
                'rule_type': row[3],
                'subject_element_type': row[4],
                'relationship_type': row[5],
                'target_element_type': row[6],
                'conditions': json.loads(row[7]) if row[7] else None,
                'active': bool(row[8]),
                'created_at': row[9],
                'updated_at': row[10]
            })
        
        cur.close()
        conn.close()
        return jsonify(rules)
    except Exception as e:
        if conn:
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/design-rules', methods=['POST'])
def create_design_rule():
    """Create a new design rule"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        required_fields = ['name', 'rule_type', 'subject_element_type']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO design_rules
            (name, description, rule_type, subject_element_type, relationship_type,
             target_element_type, conditions_json, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['name'],
            data.get('description'),
            data['rule_type'],
            data['subject_element_type'],
            data.get('relationship_type'),
            data.get('target_element_type'),
            json.dumps(data.get('conditions')) if data.get('conditions') is not None else None,
            data.get('active', True)
        ))
        
        rule_id = cur.lastrowid
        conn.commit()
        
        # Evaluate the rule immediately
        evaluate_design_rule(cur, rule_id)
        conn.commit()
        
        cur.close()
        conn.close()
        return jsonify({'id': rule_id, 'message': 'Rule created successfully'}), 201
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/design-rules/<int:rule_id>', methods=['GET'])
def get_design_rule(rule_id):
    """Get a specific design rule"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT id, name, description, rule_type, subject_element_type,
                   relationship_type, target_element_type, conditions_json, active,
                   created_at, updated_at
            FROM design_rules
            WHERE id = ?
        ''', (rule_id,))
        
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return jsonify({'error': 'Rule not found'}), 404
        
        rule = {
            'id': row[0],
            'name': row[1],
            'description': row[2],
            'rule_type': row[3],
            'subject_element_type': row[4],
            'relationship_type': row[5],
            'target_element_type': row[6],
            'conditions': json.loads(row[7]) if row[7] else None,
            'active': bool(row[8]),
            'created_at': row[9],
            'updated_at': row[10]
        }
        
        cur.close()
        conn.close()
        return jsonify(rule)
    except Exception as e:
        if conn:
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/design-rules/<int:rule_id>', methods=['PUT'])
def update_design_rule(rule_id):
    """Update a design rule"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        cur = conn.cursor()
        
        # Check if rule exists
        cur.execute('SELECT id FROM design_rules WHERE id = ?', (rule_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'error': 'Rule not found'}), 404
        
        # Build update query dynamically
        updates = []
        params = []
        
        if 'name' in data:
            updates.append('name = ?')
            params.append(data['name'])
        if 'description' in data:
            updates.append('description = ?')
            params.append(data['description'])
        if 'rule_type' in data:
            updates.append('rule_type = ?')
            params.append(data['rule_type'])
        if 'subject_element_type' in data:
            updates.append('subject_element_type = ?')
            params.append(data['subject_element_type'])
        if 'relationship_type' in data:
            updates.append('relationship_type = ?')
            params.append(data['relationship_type'])
        if 'target_element_type' in data:
            updates.append('target_element_type = ?')
            params.append(data['target_element_type'])
        if 'conditions' in data:
            updates.append('conditions_json = ?')
            params.append(json.dumps(data.get('conditions')))
        if 'active' in data:
            updates.append('active = ?')
            params.append(data['active'])
        
        updates.append('updated_at = CURRENT_TIMESTAMP')
        params.append(rule_id)
        
        cur.execute(f'''
            UPDATE design_rules
            SET {', '.join(updates)}
            WHERE id = ?
        ''', params)
        
        conn.commit()
        
        # Always re-evaluate so inactive rules get cleared
        evaluate_design_rule(cur, rule_id)
        conn.commit()
        
        cur.close()
        conn.close()
        return jsonify({'message': 'Rule updated successfully'}), 200
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/design-rules/<int:rule_id>', methods=['DELETE'])
def delete_design_rule(rule_id):
    """Delete a design rule"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Check if rule exists
        cur.execute('SELECT id FROM design_rules WHERE id = ?', (rule_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'error': 'Rule not found'}), 404
        
        # Delete violations first (cascade should handle this, but being explicit)
        cur.execute('DELETE FROM design_rule_violations WHERE rule_id = ?', (rule_id,))
        # Delete rule-generated property instances tied to this rule (including legacy rows)
        cur.execute('DELETE FROM canvas_property_instances WHERE rule_id = ?', (rule_id,))
        
        # Delete the rule
        cur.execute('DELETE FROM design_rules WHERE id = ?', (rule_id,))
        
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'message': 'Rule deleted successfully'}), 200
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/design-rules/<int:rule_id>/evaluate', methods=['POST'])
def evaluate_design_rule_endpoint(rule_id):
    """Manually trigger evaluation of a design rule"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Check if rule exists
        cur.execute('SELECT id FROM design_rules WHERE id = ?', (rule_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'error': 'Rule not found'}), 404
        
        evaluate_design_rule(cur, rule_id)
        conn.commit()
        
        cur.close()
        conn.close()
        return jsonify({'message': 'Rule evaluated successfully'}), 200
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/design-rules/evaluate-all', methods=['POST'])
def evaluate_all_design_rules_endpoint():
    """Evaluate all active design rules"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Get all active rules
        cur.execute('SELECT id FROM design_rules WHERE active = 1')
        active_rules = cur.fetchall()
        active_rule_ids = [row[0] for row in active_rules]

        # Clear violations for inactive or deleted rules
        if active_rule_ids:
            placeholders = ','.join(['?'] * len(active_rule_ids))
            cur.execute(f'''
                DELETE FROM design_rule_violations
                WHERE rule_id NOT IN ({placeholders})
            ''', active_rule_ids)
        else:
            cur.execute('DELETE FROM design_rule_violations')
        
        # Evaluate each active rule
        for rule_row in active_rules:
            rule_id = rule_row[0]
            evaluate_design_rule(cur, rule_id)
        
        # Remove violations and rule-generated properties for impact models
        cur.execute('''
            DELETE FROM design_rule_violations
            WHERE element_instance_id IN (
                SELECT cei.id
                FROM canvas_element_instances cei
                JOIN canvas_models cm ON cei.canvas_model_id = cm.id
                WHERE cm.name LIKE 'Impact:%'
            )
        ''')
        cur.execute('''
            DELETE FROM canvas_property_instances
            WHERE (source = ? OR rule_id IS NOT NULL)
              AND element_instance_id IN (
                SELECT cei.id
                FROM canvas_element_instances cei
                JOIN canvas_models cm ON cei.canvas_model_id = cm.id
                WHERE cm.name LIKE 'Impact:%'
              )
        ''', ('rules_engine',))

        # Cleanup rule-generated properties for deleted rules
        cur.execute('''
            DELETE FROM canvas_property_instances
            WHERE rule_id IS NOT NULL
              AND rule_id NOT IN (SELECT id FROM design_rules)
        ''')
        # Cleanup legacy rule-generated properties without rule_id
        cur.execute('''
            DELETE FROM canvas_property_instances
            WHERE rule_id IS NULL AND source = ?
        ''', ('rules_engine',))
        
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'message': f'Evaluated {len(active_rules)} active rule(s) successfully'}), 200
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def build_impact_graph(cur, source_instance_id, model_id, max_depth, direction, relationship_types):
    """Build a multi-hop impact graph from a source element occurrence."""
    direction = (direction or 'both').lower()
    if direction not in ('incoming', 'outgoing', 'both'):
        direction = 'both'

    rel_types = relationship_types or []
    rel_types = [t for t in rel_types if t]

    def fetch_edges_for(instance_id, rel_direction):
        params = [model_id, instance_id]
        rel_filter = ''
        if rel_types:
            placeholders = ','.join(['?'] * len(rel_types))
            rel_filter = f' AND cr.relationship_type IN ({placeholders})'
            params += rel_types
        if rel_direction == 'incoming':
            cur.execute(f'''
                SELECT cr.source_instance_id, cr.target_instance_id, cr.relationship_type
                FROM canvas_relationships cr
                WHERE cr.canvas_model_id = ?
                  AND cr.target_instance_id = ?
                  {rel_filter}
            ''', params)
        else:
            cur.execute(f'''
                SELECT cr.source_instance_id, cr.target_instance_id, cr.relationship_type
                FROM canvas_relationships cr
                WHERE cr.canvas_model_id = ?
                  AND cr.source_instance_id = ?
                  {rel_filter}
            ''', params)
        return cur.fetchall()

    visited = {source_instance_id}
    depth_map = {source_instance_id: 0}
    edge_set = set()
    queue = deque([source_instance_id])

    while queue:
        current = queue.popleft()
        current_depth = depth_map.get(current, 0)
        if current_depth >= max_depth:
            continue

        edges = []
        if direction in ('outgoing', 'both'):
            edges.extend(fetch_edges_for(current, 'outgoing'))
        if direction in ('incoming', 'both'):
            edges.extend(fetch_edges_for(current, 'incoming'))

        for source_id, target_id, rel_type in edges:
            edge_key = (source_id, target_id, rel_type or '')
            if edge_key not in edge_set:
                edge_set.add(edge_key)

            neighbor_id = target_id if source_id == current else source_id
            if neighbor_id not in visited:
                visited.add(neighbor_id)
                depth_map[neighbor_id] = current_depth + 1
                queue.append(neighbor_id)

    return visited, depth_map, edge_set


def fetch_impact_node_details(cur, instance_ids):
    if not instance_ids:
        return {}
    placeholders = ','.join(['?'] * len(instance_ids))
    cur.execute(f'''
        SELECT
            cei.id,
            cei.instance_name,
            cei.description,
            cei.element_type_id,
            dm.element,
            dm.enterprise
        FROM canvas_element_instances cei
        JOIN domainmodel dm ON cei.element_type_id = dm.id
        WHERE cei.id IN ({placeholders})
    ''', list(instance_ids))
    return {
        row[0]: {
            'id': row[0],
            'instance_name': row[1],
            'description': row[2],
            'element_type_id': row[3],
            'element_type': row[4],
            'enterprise': row[5]
        }
        for row in cur.fetchall()
    }


def fetch_missing_node_details(cur, instance_ids):
    """Fallback fetch for missing nodes to ensure element_type_id is present."""
    if not instance_ids:
        return {}
    placeholders = ','.join(['?'] * len(instance_ids))
    cur.execute(f'''
        SELECT
            cei.id,
            cei.instance_name,
            cei.description,
            cei.element_type_id,
            dm.element,
            dm.enterprise
        FROM canvas_element_instances cei
        LEFT JOIN domainmodel dm ON cei.element_type_id = dm.id
        WHERE cei.id IN ({placeholders})
    ''', list(instance_ids))
    return {
        row[0]: {
            'id': row[0],
            'instance_name': row[1],
            'description': row[2],
            'element_type_id': row[3],
            'element_type': row[4],
            'enterprise': row[5]
        }
        for row in cur.fetchall()
    }


def build_impact_summary(nodes):
    by_enterprise = {}
    by_type = {}
    for node in nodes:
        enterprise = node.get('enterprise') or 'Unassigned'
        by_enterprise[enterprise] = by_enterprise.get(enterprise, 0) + 1
        elem_type = node.get('element_type') or 'Unknown'
        by_type[elem_type] = by_type.get(elem_type, 0) + 1
    return {
        'by_enterprise': by_enterprise,
        'by_type': by_type,
        'total_nodes': len(nodes)
    }


@app.route('/api/impact-analysis', methods=['POST'])
def impact_analysis():
    """Compute multi-hop impact analysis for a source element occurrence."""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        data = request.get_json() or {}
        source_instance_id = data.get('source_instance_id')
        model_id = data.get('model_id')
        max_depth = int(data.get('max_depth', 2))
        direction = data.get('direction', 'both')
        relationship_types = data.get('relationship_types', [])

        if not source_instance_id:
            return jsonify({'error': 'source_instance_id is required'}), 400

        cur = conn.cursor()

        if model_id:
            cur.execute('SELECT id FROM canvas_element_instances WHERE id = ? AND canvas_model_id = ?', (source_instance_id, model_id))
            if not cur.fetchone():
                cur.close()
                conn.close()
                return jsonify({'error': 'Source occurrence not found in model'}), 404
        else:
            cur.execute('SELECT canvas_model_id FROM canvas_element_instances WHERE id = ?', (source_instance_id,))
            row = cur.fetchone()
            if not row:
                cur.close()
                conn.close()
                return jsonify({'error': 'Source occurrence not found'}), 404
            model_id = row[0]

        visited, depth_map, edge_set = build_impact_graph(
            cur,
            source_instance_id,
            model_id,
            max_depth,
            direction,
            relationship_types
        )

        nodes_map = fetch_impact_node_details(cur, visited)
        missing_ids = [node_id for node_id in visited if node_id not in nodes_map]
        if missing_ids:
            nodes_map.update(fetch_missing_node_details(cur, missing_ids))
        nodes = []
        for node_id in visited:
            details = nodes_map.get(node_id, {'id': node_id})
            details['depth'] = depth_map.get(node_id, 0)
            nodes.append(details)

        edges = [
            {'source_instance_id': src, 'target_instance_id': tgt, 'relationship_type': rel}
            for (src, tgt, rel) in edge_set
        ]

        summary = build_impact_summary(nodes)
        summary['total_edges'] = len(edges)
        summary['max_depth'] = max_depth

        cur.close()
        conn.close()
        return jsonify({
            'model_id': model_id,
            'source_instance_id': source_instance_id,
            'nodes': nodes,
            'edges': edges,
            'summary': summary
        })
    except Exception as e:
        if conn:
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/impact-analysis/create-model', methods=['POST'])
def impact_analysis_create_model():
    """Create a new canvas model from impact analysis results."""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        data = request.get_json() or {}
        source_instance_id = data.get('source_instance_id')
        model_id = data.get('model_id')
        max_depth = int(data.get('max_depth', 2))
        direction = data.get('direction', 'both')
        relationship_types = data.get('relationship_types', [])

        if not source_instance_id:
            return jsonify({'error': 'source_instance_id is required'}), 400

        cur = conn.cursor()
        if model_id:
            cur.execute('SELECT id FROM canvas_element_instances WHERE id = ? AND canvas_model_id = ?', (source_instance_id, model_id))
            if not cur.fetchone():
                cur.close()
                conn.close()
                return jsonify({'error': 'Source occurrence not found in model'}), 404
        else:
            cur.execute('SELECT canvas_model_id FROM canvas_element_instances WHERE id = ?', (source_instance_id,))
            row = cur.fetchone()
            if not row:
                cur.close()
                conn.close()
                return jsonify({'error': 'Source occurrence not found'}), 404
            model_id = row[0]

        visited, depth_map, edge_set = build_impact_graph(
            cur,
            source_instance_id,
            model_id,
            max_depth,
            direction,
            relationship_types
        )

        nodes_map = fetch_impact_node_details(cur, visited)
        missing_ids = [node_id for node_id in visited if node_id not in nodes_map]
        if missing_ids:
            nodes_map.update(fetch_missing_node_details(cur, missing_ids))
        nodes = []
        for node_id in visited:
            details = nodes_map.get(node_id, {'id': node_id})
            details['depth'] = depth_map.get(node_id, 0)
            nodes.append(details)

        summary = build_impact_summary(nodes)

        cur.execute('SELECT instance_name FROM canvas_element_instances WHERE id = ?', (source_instance_id,))
        source_name_row = cur.fetchone()
        source_name = source_name_row[0] if source_name_row else 'Impact'

        ok, error = enforce_model_limit(conn)
        if not ok:
            cur.close()
            conn.close()
            return jsonify(error), 403

        ok, error = enforce_element_occurrence_limit(conn, occurrences_to_add=len(nodes))
        if not ok:
            cur.close()
            conn.close()
            return jsonify(error), 403

        model_name = f'Impact: {source_name}'
        model_description = f'Impact analysis from "{source_name}" (depth {max_depth})'
        canvas_width = max(2000, 800 + (max_depth * 450))
        canvas_height = canvas_width

        cur.execute('''
            INSERT INTO canvas_models
            (name, description, canvas_width, canvas_height, zoom_level, pan_x, pan_y, canvas_template, template_zoom, template_pan_x, template_pan_y)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            model_name,
            model_description,
            canvas_width,
            canvas_height,
            1.0,
            0,
            0,
            'none',
            1.0,
            0,
            0
        ))
        new_model_id = cur.lastrowid

        center_x = canvas_width / 2
        center_y = canvas_height / 2
        radius_step = 260

        children = {node['id']: [] for node in nodes}
        for source_id, target_id, _rel_type in edge_set:
            source_depth = depth_map.get(source_id)
            target_depth = depth_map.get(target_id)
            if source_depth is None or target_depth is None:
                continue
            if source_depth + 1 == target_depth:
                children[source_id].append(target_id)
            elif target_depth + 1 == source_depth:
                children[target_id].append(source_id)

        subtree_size = {}

        def compute_subtree(node_id):
            size = 1
            for child_id in children.get(node_id, []):
                size += compute_subtree(child_id)
            subtree_size[node_id] = size
            return size

        compute_subtree(source_instance_id)

        positions = {source_instance_id: (center_x, center_y)}

        def assign_positions(node_id, angle_start, angle_end):
            child_ids = children.get(node_id, [])
            if not child_ids:
                return
            total_size = sum(subtree_size.get(cid, 1) for cid in child_ids)
            current_angle = angle_start
            for child_id in child_ids:
                fraction = (subtree_size.get(child_id, 1) / total_size) if total_size else 0
                span = (angle_end - angle_start) * fraction
                child_angle_start = current_angle
                child_angle_end = current_angle + span
                child_angle = (child_angle_start + child_angle_end) / 2
                radius = depth_map.get(child_id, 1) * radius_step
                positions[child_id] = (
                    center_x + radius * math.cos(child_angle),
                    center_y + radius * math.sin(child_angle)
                )
                assign_positions(child_id, child_angle_start, child_angle_end)
                current_angle += span

        assign_positions(source_instance_id, 0, 2 * math.pi)

        unpositioned = [node for node in nodes if node['id'] not in positions]
        if unpositioned:
            angle_step = (2 * math.pi) / max(len(unpositioned), 1)
            for idx, node in enumerate(unpositioned):
                radius = depth_map.get(node['id'], 1) * radius_step
                angle = idx * angle_step
                positions[node['id']] = (
                    center_x + radius * math.cos(angle),
                    center_y + radius * math.sin(angle)
                )

        id_map = {}
        for node in nodes:
            element_type_id = node.get('element_type_id')
            if not element_type_id:
                cur.execute('SELECT element_type_id FROM canvas_element_instances WHERE id = ?', (node['id'],))
                row = cur.fetchone()
                element_type_id = row[0] if row else None
            if not element_type_id:
                continue
            position = positions.get(node['id'], (center_x, center_y))
            cur.execute('''
                INSERT INTO canvas_element_instances
                (canvas_model_id, element_type_id, instance_name, description, x_position, y_position, width, height, z_index)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                new_model_id,
                element_type_id,
                node.get('instance_name') or 'Impact Element',
                node.get('description'),
                position[0],
                position[1],
                120,
                120,
                0
            ))
            id_map[node['id']] = cur.lastrowid

        for source_id, target_id, rel_type in edge_set:
            if source_id not in id_map or target_id not in id_map:
                continue
            cur.execute('''
                INSERT INTO canvas_relationships
                (canvas_model_id, source_instance_id, target_instance_id, relationship_type, line_path)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                new_model_id,
                id_map[source_id],
                id_map[target_id],
                rel_type,
                None
            ))

        conn.commit()
        cur.close()
        conn.close()
        return jsonify({
            'model_id': new_model_id,
            'model_name': model_name,
            'summary': summary
        }), 201
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/design-rules/violations', methods=['GET'])
def get_design_rule_violations():
    """Get all design rule violations, optionally filtered"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        rule_id = request.args.get('rule_id', type=int)
        severity = request.args.get('severity')  # 'warning' or 'negative'
        element_instance_id = request.args.get('element_instance_id', type=int)
        
        cur = conn.cursor()
        
        query = '''
            SELECT 
                drv.id,
                drv.rule_id,
                dr.name as rule_name,
                drv.element_instance_id,
                cei.instance_name,
                cei.element_type_id,
                dm.element as element_type,
                drv.severity,
                drv.current_value,
                drv.threshold_value,
                drv.evaluated_at
            FROM design_rule_violations drv
            JOIN design_rules dr ON drv.rule_id = dr.id
            JOIN canvas_element_instances cei ON drv.element_instance_id = cei.id
            JOIN domainmodel dm ON cei.element_type_id = dm.id
            WHERE 1=1
        '''
        params = []
        
        if rule_id:
            query += ' AND drv.rule_id = ?'
            params.append(rule_id)
        if severity:
            query += ' AND drv.severity = ?'
            params.append(severity)
        if element_instance_id:
            query += ' AND drv.element_instance_id = ?'
            params.append(element_instance_id)
        
        query += ' ORDER BY drv.evaluated_at DESC'
        
        cur.execute(query, params)
        
        violations = []
        for row in cur.fetchall():
            violations.append({
                'id': row[0],
                'rule_id': row[1],
                'rule_name': row[2],
                'element_instance_id': row[3],
                'element_instance_name': row[4],
                'element_type_id': row[5],
                'element_type': row[6],
                'severity': row[7],
                'current_value': row[8],
                'threshold_value': row[9],
                'evaluated_at': row[10]
            })
        
        cur.close()
        conn.close()
        return jsonify(violations)
    except Exception as e:
        if conn:
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

def evaluate_design_rule(cur, rule_id):
    """Evaluate a design rule against all element instances and update violations table"""
    # Get the rule
    cur.execute('''
        SELECT name, rule_type, subject_element_type, relationship_type, target_element_type,
               conditions_json, active
        FROM design_rules
        WHERE id = ?
    ''', (rule_id,))
    
    rule = cur.fetchone()
    if not rule:
        return
    
    rule_name = rule[0]
    rule_type = rule[1]
    subject_element_type = rule[2]
    relationship_type = rule[3]
    target_element_type = rule[4]
    conditions_json = rule[5]
    active = rule[6]
    
    if not active:
        # Rule is inactive, clear violations
        cur.execute('DELETE FROM design_rule_violations WHERE rule_id = ?', (rule_id,))
        cur.execute('DELETE FROM canvas_property_instances WHERE rule_id = ?', (rule_id,))
        return
    
    # Clear existing violations for this rule
    cur.execute('DELETE FROM design_rule_violations WHERE rule_id = ?', (rule_id,))
    # Clear existing rule-generated property instances for this rule
    cur.execute('DELETE FROM canvas_property_instances WHERE rule_id = ?', (rule_id,))
    # Also remove legacy rule-generated properties saved without rule_id
    cur.execute('''
        SELECT id FROM domainelementproperties
        WHERE propertyname = ? AND element_id IS NULL
    ''', (rule_name,))
    legacy_property_ids = [row[0] for row in cur.fetchall()]
    if legacy_property_ids:
        placeholders = ','.join(['?'] * len(legacy_property_ids))
        cur.execute(f'''
            DELETE FROM canvas_property_instances
            WHERE property_id IN ({placeholders})
        ''', legacy_property_ids)
    
    # Only handle relationship_count rule types for now (outgoing/incoming)
    if rule_type in ('relationship_count', 'relationship_count_outgoing', 'relationship_count_incoming'):
        # Get all element instances of the subject type
        cur.execute('''
            SELECT 
                cei.id,
                cei.instance_name,
                cei.canvas_model_id,
                cei.x_position,
                cei.y_position,
                cei.width,
                cei.height,
                dm.element as element_type
            FROM canvas_element_instances cei
            JOIN domainmodel dm ON cei.element_type_id = dm.id
            JOIN canvas_models cm ON cei.canvas_model_id = cm.id
            WHERE (cm.name IS NULL OR cm.name NOT LIKE 'Impact:%')
              AND (LOWER(dm.element) = LOWER(?)
               OR LOWER(dm.name) = LOWER(?))
              AND cei.id IN (
                  SELECT MIN(cei2.id)
                  FROM canvas_element_instances cei2
                  JOIN canvas_models cm2 ON cei2.canvas_model_id = cm2.id
                  WHERE (cm2.name IS NULL OR cm2.name NOT LIKE 'Impact:%')
                    AND cei2.element_type_id = cei.element_type_id
                    AND LOWER(COALESCE(cei2.instance_name, '')) = LOWER(COALESCE(cei.instance_name, ''))
                  GROUP BY cei2.element_type_id, LOWER(COALESCE(cei2.instance_name, ''))
              )
        ''', (subject_element_type, subject_element_type))
        
        subject_instances = cur.fetchall()
        
        # Get relationship rules to understand what relationships are valid
        # For incoming rules, subject is target and target_element_type is the source side
        if rule_type == 'relationship_count_incoming':
            cur.execute('''
                SELECT DISTINCT dm1.id as source_id, dm2.id as target_id
                FROM domainmodelrelationship dmr
                JOIN domainmodel dm1 ON dmr.source_element_id = dm1.id
                JOIN domainmodel dm2 ON dmr.target_element_id = dm2.id
                WHERE LOWER(dm2.element) = LOWER(?)
                  AND LOWER(dm1.element) = LOWER(?)
                  AND (dmr.relationship_type = ? OR ? IS NULL)
            ''', (subject_element_type, target_element_type, relationship_type, relationship_type))
        else:
            cur.execute('''
                SELECT DISTINCT dm1.id as source_id, dm2.id as target_id
                FROM domainmodelrelationship dmr
                JOIN domainmodel dm1 ON dmr.source_element_id = dm1.id
                JOIN domainmodel dm2 ON dmr.target_element_id = dm2.id
                WHERE LOWER(dm1.element) = LOWER(?)
                  AND LOWER(dm2.element) = LOWER(?)
                  AND (dmr.relationship_type = ? OR ? IS NULL)
            ''', (subject_element_type, target_element_type, relationship_type, relationship_type))
        
        relationship_rules = cur.fetchall()
        if not relationship_rules and not conditions_json:
            # No valid relationship rules found, can't evaluate
            return
        
        # Get element type IDs for the opposite side of the relationship (fallback rules only)
        target_type_ids = []
        if relationship_rules:
            target_type_ids = [row[0] for row in relationship_rules] if rule_type == 'relationship_count_incoming' else [row[1] for row in relationship_rules]
        
        def get_rule_property_id(severity_label):
            ragtype = severity_label.capitalize()
            image_map = {
                'Negative': '/images/Tag-Red.svg',
                'Warning': '/images/Tag-Yellow.svg',
                'Positive': '/images/Tag-Green.svg'
            }
            image_url = image_map.get(ragtype)
            cur.execute('''
                SELECT id FROM domainelementproperties
                WHERE propertyname = ? AND LOWER(ragtype) = LOWER(?) AND element_id IS NULL
            ''', (rule_name, ragtype))
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute('''
                INSERT INTO domainelementproperties
                (element_id, ragtype, propertyname, description, image_url, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ''', (None, ragtype, rule_name, f'Auto-generated by rules engine for rule "{rule_name}"', image_url))
            return cur.lastrowid

        try:
            parsed_conditions = json.loads(conditions_json) if conditions_json else None
        except Exception as e:
            logging.warning("Invalid conditions_json for rule_id=%s (%s): %s", rule_id, rule_name, e)
            parsed_conditions = None

        # Query Logic is required; skip evaluation if no conditions are defined.
        if not parsed_conditions:
            return

        subject_type_ids = []
        cur.execute(
            'SELECT id FROM domainmodel WHERE LOWER(element) = LOWER(?) OR LOWER(name) = LOWER(?)',
            (subject_element_type, subject_element_type)
        )
        subject_type_ids = [row[0] for row in cur.fetchall()]

        def fetch_related_type_ids(direction, related_element_type, rel_type):
            if not related_element_type:
                cur.execute('SELECT id FROM domainmodel')
                return [row[0] for row in cur.fetchall()]
            if direction == 'incoming':
                cur.execute('''
                    SELECT DISTINCT dm1.id as source_id, dm2.id as target_id
                    FROM domainmodelrelationship dmr
                    JOIN domainmodel dm1 ON dmr.source_element_id = dm1.id
                    JOIN domainmodel dm2 ON dmr.target_element_id = dm2.id
                    WHERE LOWER(dm2.element) = LOWER(?)
                      AND LOWER(dm1.element) = LOWER(?)
                      AND (dmr.relationship_type = ? OR ? IS NULL)
                ''', (subject_element_type, related_element_type, rel_type, rel_type))
                related_ids = [row[0] for row in cur.fetchall()]
                if related_ids:
                    return related_ids
                if related_element_type:
                    cur.execute(
                        'SELECT id FROM domainmodel WHERE LOWER(element) = LOWER(?) OR LOWER(name) = LOWER(?)',
                        (related_element_type, related_element_type)
                    )
                    return [row[0] for row in cur.fetchall()]
                return []
            cur.execute('''
                SELECT DISTINCT dm1.id as source_id, dm2.id as target_id
                FROM domainmodelrelationship dmr
                JOIN domainmodel dm1 ON dmr.source_element_id = dm1.id
                JOIN domainmodel dm2 ON dmr.target_element_id = dm2.id
                WHERE LOWER(dm1.element) = LOWER(?)
                  AND LOWER(dm2.element) = LOWER(?)
                  AND (dmr.relationship_type = ? OR ? IS NULL)
            ''', (subject_element_type, related_element_type, rel_type, rel_type))
            related_ids = [row[1] for row in cur.fetchall()]
            if related_ids:
                return related_ids
            if related_element_type:
                cur.execute(
                    'SELECT id FROM domainmodel WHERE LOWER(element) = LOWER(?) OR LOWER(name) = LOWER(?)',
                    (related_element_type, related_element_type)
                )
                return [row[0] for row in cur.fetchall()]
            return []
        
        def get_related_instances(instance_id, direction, target_type_ids, rel_type):
            if not target_type_ids:
                return [], 0
            if direction == 'incoming':
                cur.execute('''
                    SELECT DISTINCT 
                        source_cei.id,
                        source_cei.instance_name,
                        source_cei.canvas_model_id,
                        source_cei.x_position,
                        source_cei.y_position,
                        source_cei.width,
                        source_cei.height,
                        dm.element as element_type
                    FROM canvas_relationships cr
                    JOIN canvas_element_instances source_cei ON cr.source_instance_id = source_cei.id
                    JOIN domainmodel dm ON source_cei.element_type_id = dm.id
                    WHERE cr.target_instance_id = ?
                      AND source_cei.element_type_id IN ({})
                      AND (cr.relationship_type = ? OR ? IS NULL)
                '''.format(','.join(['?'] * len(target_type_ids))),
                    [instance_id] + target_type_ids + [rel_type, rel_type])
                rows = cur.fetchall()
                return rows, len(rows)
            cur.execute('''
                SELECT DISTINCT 
                    target_cei.id,
                    target_cei.instance_name,
                    target_cei.canvas_model_id,
                    target_cei.x_position,
                    target_cei.y_position,
                    target_cei.width,
                    target_cei.height,
                    dm.element as element_type
                FROM canvas_relationships cr
                JOIN canvas_element_instances target_cei ON cr.target_instance_id = target_cei.id
                JOIN domainmodel dm ON target_cei.element_type_id = dm.id
                WHERE cr.source_instance_id = ?
                  AND target_cei.element_type_id IN ({})
                  AND (cr.relationship_type = ? OR ? IS NULL)
            '''.format(','.join(['?'] * len(target_type_ids))),
                [instance_id] + target_type_ids + [rel_type, rel_type])
            rows = cur.fetchall()
            return rows, len(rows)
        
        def apply_rule_property(affected, severity, current_value, threshold_value):
            affected_id = affected[0]
            affected_canvas_model_id = affected[2]
            affected_x = affected[3]
            affected_y = affected[4]
            affected_width = affected[5] or 120
            affected_height = affected[6] or 120
            affected_element_type = affected[7] or ''
            
            cur.execute('''
                INSERT INTO design_rule_violations
                (rule_id, element_instance_id, severity, current_value, threshold_value)
                VALUES (?, ?, ?, ?, ?)
            ''', (rule_id, affected_id, severity, current_value, threshold_value))
            
            property_id = get_rule_property_id(severity)
            # Deduplicate any prior rule-generated properties for this element/property
            cur.execute('''
                DELETE FROM canvas_property_instances
                WHERE element_instance_id = ?
                  AND property_id = ?
                  AND source = ?
            ''', (affected_id, property_id, 'rules_engine'))
            cur.execute('''
                SELECT id FROM canvas_property_instances
                WHERE element_instance_id = ? AND rule_id = ?
            ''', (affected_id, rule_id))
            if cur.fetchone():
                return
            cur.execute('SELECT COUNT(*) FROM canvas_property_instances WHERE element_instance_id = ?', (affected_id,))
            existing_count = cur.fetchone()[0]
            
            property_width = 120
            property_height = 40
            is_people = affected_element_type.lower() == 'people'
            label_height = 20 if is_people else 0
            property_x = affected_x - (property_width - affected_width) / 2 if is_people else affected_x
            property_y = affected_y + affected_height + label_height + (existing_count * property_height)
            
            cur.execute('''
                INSERT INTO canvas_property_instances
                (canvas_model_id, property_id, element_instance_id, instance_name, x_position, y_position, width, height, z_index, source, rule_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                affected_canvas_model_id,
                property_id,
                affected_id,
                rule_name,
                property_x,
                property_y,
                property_width,
                property_height,
                0,
                'rules_engine',
                rule_id
            ))
        
        for subject_instance in subject_instances:
            instance_id = subject_instance[0]
            canvas_model_id = subject_instance[2]
            x_position = subject_instance[3]
            y_position = subject_instance[4]
            width = subject_instance[5] or 120
            height = subject_instance[6] or 120
            element_type = subject_instance[7] or ''

            groups = []
            current_group = None
            for row in parsed_conditions:
                conj = (row.get('conjunction') or 'where').lower()
                if conj == 'where' or current_group is None:
                    current_group = {
                        'severity': (row.get('severity') or '').lower(),
                        'property_target': (row.get('property_target') or 'subject').lower(),
                        'conditions': []
                    }
                    groups.append(current_group)
                current_group['conditions'].append(row)
            
            for group in groups:
                result = None
                first_count = None
                first_threshold = None
                first_related = []
                first_direction = 'outgoing'
                for idx, cond in enumerate(group['conditions']):
                    direction = (cond.get('direction') or 'outgoing').lower()
                    rel_type = cond.get('relationship_type') or None
                    related_type = cond.get('related_element_type') or ''
                    op = (cond.get('operator') or 'eq').lower()
                    right_value_raw = cond.get('right_count', cond.get('count'))
                    right_value = int(right_value_raw) if right_value_raw not in (None, '') else 0
                    left_value_raw = cond.get('left_count')
                    left_value = int(left_value_raw) if left_value_raw not in (None, '') else None
                    text_value = (cond.get('text_value') or '').strip().lower()
                    
                    related_type_ids = fetch_related_type_ids(direction, related_type, rel_type)
                    related_instances, count = get_related_instances(instance_id, direction, related_type_ids, rel_type)
                    if idx == 0:
                        first_count = count
                        first_threshold = right_value
                        first_related = related_instances
                        first_direction = direction
                    
                    cond_result = False
                    if op == 'text':
                        if text_value:
                            cond_result = any(
                                text_value in (rel[1] or '').lower()
                                for rel in related_instances
                            )
                    else:
                        if op == 'eq':
                            cond_result = count == right_value
                        elif op == 'gt':
                            cond_result = count > right_value
                        elif op == 'lt':
                            cond_result = count < right_value
                        elif op == 'gte':
                            cond_result = count >= right_value
                        elif op == 'lte':
                            cond_result = count <= right_value

                    if cond_result and left_value is not None and related_instances and subject_type_ids:
                        left_ok = False
                        for rel in related_instances:
                            related_id = rel[0]
                            if direction == 'incoming':
                                cur.execute('''
                                    SELECT COUNT(DISTINCT cr.target_instance_id)
                                    FROM canvas_relationships cr
                                    JOIN canvas_element_instances target_cei ON cr.target_instance_id = target_cei.id
                                    WHERE cr.source_instance_id = ?
                                      AND target_cei.element_type_id IN ({})
                                      AND (cr.relationship_type = ? OR ? IS NULL)
                                '''.format(','.join(['?'] * len(subject_type_ids))),
                                    [related_id] + subject_type_ids + [rel_type, rel_type])
                            else:
                                cur.execute('''
                                    SELECT COUNT(DISTINCT cr.source_instance_id)
                                    FROM canvas_relationships cr
                                    JOIN canvas_element_instances source_cei ON cr.source_instance_id = source_cei.id
                                    WHERE cr.target_instance_id = ?
                                      AND source_cei.element_type_id IN ({})
                                      AND (cr.relationship_type = ? OR ? IS NULL)
                                '''.format(','.join(['?'] * len(subject_type_ids))),
                                    [related_id] + subject_type_ids + [rel_type, rel_type])
                            reverse_count = cur.fetchone()[0]
                            if reverse_count == left_value:
                                left_ok = True
                                break
                        cond_result = left_ok
                    
                    if result is None:
                        result = cond_result
                    else:
                        conj = (cond.get('conjunction') or 'and').lower()
                        if conj == 'or':
                            result = result or cond_result
                        else:
                            result = result and cond_result
                
                if result and group['severity']:
                    if group['property_target'] == 'target' or group['property_target'] == 'targets':
                        affected_list = first_related if first_direction == 'outgoing' else first_related
                    elif group['property_target'] == 'sources':
                        affected_list = first_related if first_direction == 'incoming' else [(instance_id, subject_instance[1], canvas_model_id, x_position, y_position, width, height, element_type)]
                    else:
                        affected_list = [(instance_id, subject_instance[1], canvas_model_id, x_position, y_position, width, height, element_type)]
                    
                    for affected in affected_list:
                        apply_rule_property(affected, group['severity'], first_count or 0, first_threshold or 0)


@app.route('/api/relationships', methods=['GET'])
def get_relationships():
    """Get all relationships with element names, optionally filtered by enterprise/repository"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        enterprise_filter = request.args.get('enterprise', None)
        cur = conn.cursor()
        
        if enterprise_filter:
            # Filter relationships where both source and target elements belong to the specified enterprise
            cur.execute('''
                SELECT 
                    r.id,
                    r.source_element_id,
                    s.name AS source_element_name,
                    s.image_url AS source_image_url,
                    s.facet AS source_facet,
                    s.enterprise AS source_enterprise,
                    r.target_element_id,
                    t.name AS target_element_name,
                    t.image_url AS target_image_url,
                    t.facet AS target_facet,
                    t.enterprise AS target_enterprise,
                    r.relationship_type,
                    r.description,
                    r.created_at,
                    r.updated_at
                FROM domainmodelrelationship r
                JOIN domainmodel s ON r.source_element_id = s.id
                JOIN domainmodel t ON r.target_element_id = t.id
                WHERE s.enterprise = ? AND t.enterprise = ?
                ORDER BY r.id DESC
            ''', (enterprise_filter, enterprise_filter))
        else:
            # Get all relationships
            cur.execute('''
                SELECT 
                    r.id,
                    r.source_element_id,
                    s.name AS source_element_name,
                    s.image_url AS source_image_url,
                    s.facet AS source_facet,
                    s.enterprise AS source_enterprise,
                    r.target_element_id,
                    t.name AS target_element_name,
                    t.image_url AS target_image_url,
                    t.facet AS target_facet,
                    t.enterprise AS target_enterprise,
                r.relationship_type,
                r.description,
                r.created_at,
                r.updated_at
            FROM domainmodelrelationship r
            JOIN domainmodel s ON r.source_element_id = s.id
            JOIN domainmodel t ON r.target_element_id = t.id
            ORDER BY r.id DESC
        ''')
        columns = [desc[0] for desc in cur.description]
        relationships = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify(relationships)
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/relationship-types', methods=['GET'])
def get_relationship_types():
    """Get all unique relationship types from the database"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('SELECT DISTINCT relationship_type FROM domainmodelrelationship ORDER BY relationship_type')
        relationship_types = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify(relationship_types)
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/relationships', methods=['POST'])
def add_relationship():
    """Add a new relationship"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.json
        source_id = data.get('source_element_id')
        target_id = data.get('target_element_id')
        
        # Prevent self-reference
        if source_id == target_id:
            return jsonify({'error': 'Source and target elements cannot be the same'}), 400
        
        # Get source and target element details (including enterprise for validation)
        cur = conn.cursor()
        cur.execute('SELECT name, element, enterprise FROM domainmodel WHERE id = ?', (source_id,))
        source_record = cur.fetchone()
        cur.execute('SELECT name, element, enterprise FROM domainmodel WHERE id = ?', (target_id,))
        target_record = cur.fetchone()
        
        if not source_record or not target_record:
            return jsonify({'error': 'Source or target element not found'}), 400
        
        # Validate repository scoping: ensure both elements belong to the same enterprise
        source_enterprise = source_record[2] if len(source_record) > 2 else None
        target_enterprise = target_record[2] if len(target_record) > 2 else None
        
        # Both elements must have the same enterprise (or both be null for cross-enterprise relationships)
        # For now, we enforce same-enterprise relationships only
        if source_enterprise and target_enterprise:
            if source_enterprise.lower() != target_enterprise.lower():
                return jsonify({
                    'error': f'Repository scoping violation: Source element belongs to repository "{source_enterprise}" but target element belongs to repository "{target_enterprise}". Relationships must be within the same repository.'
                }), 400
        elif source_enterprise or target_enterprise:
            # One has enterprise, one doesn't - not allowed
            return jsonify({
                'error': 'Repository scoping violation: Both source and target elements must belong to the same repository, or both must be repository-agnostic.'
            }), 400
        
        # Use Element column for validation (fallback to name if element is null)
        source_element = (source_record[1] or source_record[0] or '').strip()
        target_element = (target_record[1] or target_record[0] or '').strip()
        relationship_type = data.get('relationship_type')
        
        # Get facet information for validation
        cur.execute('SELECT facet FROM domainmodel WHERE id = ?', (source_id,))
        source_facet_result = cur.fetchone()
        source_facet = source_facet_result[0] if source_facet_result else None
        cur.execute('SELECT facet FROM domainmodel WHERE id = ?', (target_id,))
        target_facet_result = cur.fetchone()
        target_facet = target_facet_result[0] if target_facet_result else None
        
        # Validate EDGY rules - enforce known patterns, but allow flexibility for other relationships
        # Use Element column for validation, not Name
        source_lower = source_element.lower()
        target_lower = target_element.lower()
        
        # Validate known EDGY patterns if they match
        if relationship_type in ['performs', 'uses', 'achieves']:
            # Base Facet relationships: People -> Activity/Object/Outcome (enforce for People, allow for others)
            if source_lower == 'people':
                expected_targets = {
                    'performs': 'activity',
                    'uses': 'object',
                    'achieves': 'outcome'
                }
                expected_target = expected_targets.get(relationship_type)
                if target_lower != expected_target:
                    return jsonify({'error': f'For People "{relationship_type}" relationship, target must be "{expected_target}"'}), 400
            # Allow other sources with these relationship types
        
        elif relationship_type == 'capability_requires_asset':
            # Capability requires Asset
            if source_lower != 'capability':
                return jsonify({'error': 'For "Capability requires Asset" relationship, source must be Capability'}), 400
            if target_lower != 'asset':
                return jsonify({'error': 'For "Capability requires Asset" relationship, target must be Asset'}), 400
        
        elif relationship_type == 'process_requires_asset':
            # Process requires Asset
            if source_lower != 'process':
                return jsonify({'error': 'For "Process requires Asset" relationship, source must be Process'}), 400
            if target_lower != 'asset':
                return jsonify({'error': 'For "Process requires Asset" relationship, target must be Asset'}), 400
        
        elif relationship_type == 'realises':
            # Process realises Capability
            if source_lower != 'process':
                return jsonify({'error': 'For "Process realises Capability" relationship, source must be Process'}), 400
            if target_lower != 'capability':
                return jsonify({'error': 'For "Process realises Capability" relationship, target must be Capability'}), 400
        
        elif relationship_type == 'flow':
            # Process flows to Process
            if source_lower != 'process':
                return jsonify({'error': 'For "flow" relationship, source must be Process'}), 400
            if target_lower != 'process':
                return jsonify({'error': 'For "flow" relationship, target must be Process'}), 400
        
        elif relationship_type == 'expresses':
            # Content expresses Purpose
            if source_lower != 'content':
                return jsonify({'error': 'For "Content expresses Purpose" relationship, source must be Content'}), 400
            if target_lower != 'purpose':
                return jsonify({'error': 'For "Content expresses Purpose" relationship, target must be Purpose'}), 400
        
        elif relationship_type == 'conveys':
            # Content conveys Story
            if source_lower != 'content':
                return jsonify({'error': 'For "Content conveys Story" relationship, source must be Content'}), 400
            if target_lower != 'story':
                return jsonify({'error': 'For "Content conveys Story" relationship, target must be Story'}), 400
        
        elif relationship_type == 'contextualises':
            # Story contextualises Purpose
            if source_lower != 'story':
                return jsonify({'error': 'For "Story contextualises Purpose" relationship, source must be Story'}), 400
            if target_lower != 'purpose':
                return jsonify({'error': 'For "Story contextualises Purpose" relationship, target must be Purpose'}), 400
        
        # Allow other relationship types and combinations - no strict validation needed
        
        # Check for existing relationship
        cur.execute('''
            SELECT id FROM domainmodelrelationship 
            WHERE source_element_id = ? AND target_element_id = ? AND relationship_type = ?
        ''', (source_id, target_id, relationship_type))
        if cur.fetchone():
            return jsonify({'error': 'This relationship already exists'}), 400
        cur.execute('''
            INSERT INTO domainmodelrelationship 
            (source_element_id, target_element_id, relationship_type, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ''', (
            source_id,
            target_id,
            data.get('relationship_type'),
            data.get('description')
        ))
        conn.commit()
        relationship_id = cur.lastrowid
        cur.execute('SELECT * FROM domainmodelrelationship WHERE id = ?', (relationship_id,))
        columns = [desc[0] for desc in cur.description]
        relationship = dict(zip(columns, cur.fetchone()))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify(relationship), 201
    except Exception as e:
        if conn:
            conn.close()
        error_msg = str(e)
        if 'unique_relationship' in error_msg.lower():
            return jsonify({'error': 'This relationship already exists'}), 400
        return jsonify({'error': error_msg}), 500

@app.route('/api/relationships/<int:relationship_id>', methods=['DELETE'])
def delete_relationship(relationship_id):
    """Delete a relationship"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM domainmodelrelationship WHERE id = ?', (relationship_id,))
        conn.commit()
        # Check if row was deleted
        if cur.rowcount == 0:
            cur.close()
            conn.close()
            return jsonify({'error': 'Relationship not found'}), 404
        # Fetch the deleted relationship details before closing
        cur.execute('SELECT * FROM domainmodelrelationship WHERE id = ?', (relationship_id,))
        deleted_rel = cur.fetchone()
        if deleted_rel:
            columns = [desc[0] for desc in cur.description]
            relationship = dict(zip(columns, deleted_rel))
        else:
            relationship = {'id': relationship_id}
        result = cur.fetchone()
        if not result:
            cur.close()
            conn.close()
            return jsonify({'error': 'Relationship not found'}), 404
        
        columns = [desc[0] for desc in cur.description]
        relationship = dict(zip(columns, result))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'message': 'Relationship deleted successfully', 'relationship': relationship})
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

def wrap_text(text, max_width=60):
    """Wrap text to max_width characters, breaking at word boundaries.
    Returns a list of lines (without newlines)."""
    # Ensure text is a string
    text = str(text) if text is not None else ""
    if not text or len(text) <= max_width:
        return [text] if text else []
    
    words = text.split()
    lines = []
    current_line = []
    current_length = 0
    
    for word in words:
        # Add 1 for space if not first word on line
        word_length = len(word) + (1 if current_length > 0 else 0)
        
        if current_length + word_length <= max_width:
            current_line.append(word)
            current_length += word_length
        else:
            # Start new line
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
            current_length = len(word)
    
    # Add remaining line
    if current_line:
        lines.append(' '.join(current_line))
    
    return lines


def search_web_for_context(question):
    """
    Search the web for relevant content to enhance chatbot context.
    Uses DuckDuckGo search API (via ddgs library).
    Returns tuple of (formatted_results_string, citations_list) or (None, None) on error.
    """
    try:
        # Try to import ddgs library (formerly duckduckgo_search)
        try:
            from ddgs import DDGS
        except ImportError:
            print("[Web Search] ddgs library not installed. Install with: pip install ddgs")
            return None, None
        
        # Extract key terms from the question for better search
        question_lower = question.lower()
        
        # Build focused search query specifically for Enterprise Design and EDGY content
        # Always include EDGY and Enterprise Design terminology to get relevant results
        
        # Check if question already contains EDGY-specific terms
        edgy_keywords = ['edgy', 'enterprise design', 'facets', 'base facet', 'architecture facet', 
                        'identity facet', 'experience facet', 'capability', 'asset', 'process', 'purpose', 'content', 
                        'story', 'activity', 'outcome', 'object', 'people', 'channel', 'journey', 'task',
                        'product', 'organisation', 'organization', 'brand']
        
        has_edgy_keywords = any(keyword in question_lower for keyword in edgy_keywords)
        
        # Build focused search query with Enterprise Design context
        if has_edgy_keywords:
            # Question already has EDGY terms, reinforce with Enterprise Design context
            search_query = f'"EDGY" "Enterprise Design" {question}'
        else:
            # Question doesn't have EDGY terms, add comprehensive Enterprise Design context
            search_query = f'"EDGY Enterprise Design" framework {question}'
        
        # Additional search terms to improve relevance
        search_query += " -generic -general tutorial guide"
        
        # Perform web search
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(
                    search_query,
                    max_results=5,  # Get more results to filter for Enterprise Design/EDGY relevance
                    region='wt-wt',  # Worldwide
                    safesearch='moderate'
                ))
                
                if results:
                    formatted_results = []
                    citations = []
                    
                    # EDGY and Enterprise Design relevance keywords for filtering
                    relevance_keywords = ['edgy', 'enterprise design', 'enterprise architecture', 
                                         'capability', 'asset', 'process', 'facets', 'facet',
                                         'enterprise modeling', 'business architecture', 'domain model']
                    
                    for i, result in enumerate(results, 1):
                        title = result.get('title', '')
                        body = result.get('body', '')
                        href = result.get('href', '')
                        
                        if title and body:
                            # Calculate relevance score based on EDGY/Enterprise Design keywords
                            title_lower = title.lower()
                            body_lower = body.lower()
                            relevance_score = sum(1 for keyword in relevance_keywords 
                                                if keyword in title_lower or keyword in body_lower)
                            
                            # Only include results with some relevance to Enterprise Design/EDGY
                            # Prioritize results with EDGY or Enterprise Design terms
                            if relevance_score > 0 or 'edgy' in body_lower or 'enterprise design' in body_lower:
                                # Truncate body to 250 characters
                                body_truncated = body[:250] + '...' if len(body) > 250 else body
                                
                                # Format with citation number
                                citation_num = len(citations) + 1
                                formatted_results.append(f"{i}. {title}: {body_truncated} [{citation_num}]")
                                
                                # Store citation with URL
                                if href:
                                    citations.append({
                                        'number': citation_num,
                                        'title': title,
                                        'url': href
                                    })
                                    
                                # Limit to top 3 most relevant results
                                if len(formatted_results) >= 3:
                                    break
                    
                    if formatted_results:
                        # Format citations for display
                        citations_text = "\n\nCitations:\n"
                        for citation in citations:
                            citations_text += f"[{citation['number']}] {citation['title']}\n   {citation['url']}\n"
                        
                        # Combine results with citations
                        full_text = "\n".join(formatted_results) + citations_text
                        return full_text, citations
        except Exception as e:
            print(f"[Web Search] Error performing search: {e}")
            return None, None
        
        return None, None
        
    except Exception as e:
        print(f"[Web Search] Error: {e}")
        return None, None


def normalize_element_type_to_singular(text):
    """
    Normalize plural element type forms to singular for fuzzy matching.
    Returns a dictionary mapping plural forms to singular element types.
    """
    # Mapping of plural forms to singular element types
    plural_to_singular = {
        # Base Facet
        'people': 'people',  # People is already plural
        'activities': 'activity',
        'outcomes': 'outcome',
        'objects': 'object',
        # Architecture Facet
        'capabilities': 'capability',
        'assets': 'asset',
        'processes': 'process',
        # Identity Facet
        'purposes': 'purpose',
        'contents': 'content',
        'stories': 'story',
        # Experience Facet
        'channels': 'channel',
        'journeys': 'journey',
        "journey's": 'journey',  # Handle possessive form
        'tasks': 'task',
        # Intersection Elements
        'products': 'product',
        'organisations': 'organisation',
        'organizations': 'organization',
        'brands': 'brand',
    }
    
    # Also handle common irregular plurals and variations
    text_lower = text.lower().strip()
    
    # Check if text matches any plural form
    if text_lower in plural_to_singular:
        return plural_to_singular[text_lower]
    
    # Handle possessive forms (e.g., "Journey's" -> "journey")
    if text_lower.endswith("'s"):
        base = text_lower[:-2]
        if base in plural_to_singular:
            return plural_to_singular[base]
        return base  # Return without possessive
    
    # Handle standard pluralization rules
    # Words ending in 'ies' -> 'y' (e.g., "capabilities" -> "capability")
    if text_lower.endswith('ies'):
        singular = text_lower[:-3] + 'y'
        if singular in ['capability', 'activity']:
            return singular
    
    # Words ending in 'es' -> remove 'es' (e.g., "processes" -> "process")
    if text_lower.endswith('es') and len(text_lower) > 2:
        singular = text_lower[:-2]
        if singular in ['process', 'purpose', 'journey']:
            return singular
    
    # Words ending in 's' -> remove 's' (e.g., "assets" -> "asset")
    if text_lower.endswith('s') and len(text_lower) > 1:
        singular = text_lower[:-1]
        if singular in ['asset', 'object', 'outcome', 'content', 'story', 'channel', 'task', 'product', 'organisation', 'organization', 'brand']:
            return singular
    
    # If no match found, return original text
    return text


@app.route('/api/enterprises', methods=['GET'])
def get_enterprises():
    """Get list of enterprise names from domainmodel table (for filtering)"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('SELECT DISTINCT enterprise FROM domainmodel WHERE enterprise IS NOT NULL ORDER BY enterprise')
        enterprises = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify(enterprises)
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500


@app.route('/api/chat', methods=['POST'])
def chat():
    """EDGY Assistant chatbot endpoint using Gemini LLM"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.json
        question = data.get('question', '').strip()
        enterprise_filter = data.get('enterprise', None)
        
        # Clean and validate enterprise filter
        if enterprise_filter:
            enterprise_filter = enterprise_filter.strip()
            if not enterprise_filter:  # Empty string becomes None
                enterprise_filter = None
        
        print(f"[Chat] Question: {question[:50]}... | Enterprise filter: {enterprise_filter}")
        
        cur = conn.cursor()
        
        # Get Element Types (definitions) from domainmodel table
        # These are the element type definitions (e.g., "People", "Capability", "Process")
        if enterprise_filter:
            cur.execute('''
                SELECT 
                    id,
                    name,
                    element AS element_type,
                    facet,
                    enterprise,
                    description,
                    image_url
                FROM domainmodel
                WHERE enterprise = ? 
                   OR LOWER(element) IN ('product', 'organisation', 'organization', 'brand')
                ORDER BY facet, element, name
            ''', (enterprise_filter,))
            print(f"[Chat] Loading element types filtered by enterprise: {enterprise_filter}")
        else:
            cur.execute('''
                SELECT 
                    id,
                    name,
                    element AS element_type,
                    facet,
                    enterprise,
                    description,
                    image_url
                FROM domainmodel
                ORDER BY facet, element, name
            ''')
            print("[Chat] Loading all element types (no enterprise filter)")
        
        element_types = cur.fetchall()
        
        # Format element types for context
        element_types_context = []
        for elem_type in element_types:
            element_types_context.append({
                'id': elem_type[0],
                'name': elem_type[1],
                'element_type': elem_type[2],
                'facet': elem_type[3],
                'enterprise': elem_type[4],
                'description': elem_type[5],
                'image_url': elem_type[6] if len(elem_type) > 6 else None,
                'is_element_type': True  # Flag to distinguish from occurrences
            })
        
        # Get Element Occurrences (instances) from canvas_element_instances table
        # These are actual instances of elements (e.g., "John Doe" instance of "People" type)
        if enterprise_filter:
            cur.execute('''
                SELECT 
                    cei.id,
                    cei.instance_name,
                    cei.element_type_id,
                    dm.name AS element_type_name,
                    dm.element AS element_type,
                    dm.facet,
                    dm.enterprise,
                    dm.description AS element_type_description,
                    dm.image_url,
                    cm.name AS model_name
                FROM canvas_element_instances cei
                JOIN domainmodel dm ON cei.element_type_id = dm.id
                LEFT JOIN canvas_models cm ON cei.canvas_model_id = cm.id
                WHERE dm.enterprise = ? 
                   OR LOWER(dm.element) IN ('product', 'organisation', 'organization', 'brand')
                ORDER BY cei.id
            ''', (enterprise_filter,))
            print(f"[Chat] Loading element occurrences filtered by enterprise: {enterprise_filter}")
        else:
            cur.execute('''
                SELECT 
                    cei.id,
                    cei.instance_name,
                    cei.element_type_id,
                    dm.name AS element_type_name,
                    dm.element AS element_type,
                    dm.facet,
                    dm.enterprise,
                    dm.description AS element_type_description,
                    dm.image_url,
                    cm.name AS model_name
                FROM canvas_element_instances cei
                JOIN domainmodel dm ON cei.element_type_id = dm.id
                LEFT JOIN canvas_models cm ON cei.canvas_model_id = cm.id
                ORDER BY cei.id
            ''')
            print("[Chat] Loading all element occurrences (no enterprise filter)")
        
        element_instances = cur.fetchall()
        
        # Format element occurrences for context
        element_occurrences_context = []
        for instance in element_instances:
            element_occurrences_context.append({
                'id': instance[0],
                'name': instance[1],  # instance_name
                'type_id': instance[2],
                'type_name': instance[3],
                'element_type': instance[4],
                'facet': instance[5],
                'enterprise': instance[6],
                'description': instance[7],
                'image_url': instance[8] if len(instance) > 8 else None,
                'model_name': instance[9] if len(instance) > 9 else None,
                'is_element_occurrence': True  # Flag to distinguish from types
            })
        
        # Combine both for backward compatibility (but we'll distinguish in context)
        element_context = element_types_context + element_occurrences_context
        
        # Get relationships for context - only if needed (optimize for performance)
        # Filter relationships based on enterprise if filter is set
        if enterprise_filter:
            cur.execute('''
                SELECT 
                    r.source_element_id,
                    s.name AS source_element_name,
                    r.target_element_id,
                    t.name AS target_element_name,
                    r.relationship_type
                FROM domainmodelrelationship r
                JOIN domainmodel s ON r.source_element_id = s.id
                JOIN domainmodel t ON r.target_element_id = t.id
                WHERE s.enterprise = ? OR t.enterprise = ? 
                   OR LOWER(s.element) IN ('product', 'organisation', 'organization', 'brand')
                   OR LOWER(t.element) IN ('product', 'organisation', 'organization', 'brand')
                ORDER BY r.id
            ''', (enterprise_filter, enterprise_filter))
        else:
            cur.execute('''
                SELECT 
                    r.source_element_id,
                    s.name AS source_element_name,
                    r.target_element_id,
                    t.name AS target_element_name,
                    r.relationship_type
                FROM domainmodelrelationship r
                JOIN domainmodel s ON r.source_element_id = s.id
                JOIN domainmodel t ON r.target_element_id = t.id
                ORDER BY r.id
            ''')
        relationships = cur.fetchall()
        
        # Format relationships for context
        relationship_context = []
        for rel in relationships:
            relationship_context.append({
                'source_id': rel[0],
                'source_name': rel[1],
                'target_id': rel[2],
                'target_name': rel[3],
                'type': rel[4]
            })
        
        # Get element properties for context (needed for property questions)
        # Load properties for element types (property templates/definitions)
        element_type_ids = [elem['id'] for elem in element_types_context]
        element_type_properties = {}
        if element_type_ids:
            # Get properties for element types (templates)
            placeholders = ','.join(['?' for _ in element_type_ids])
            cur.execute(f'''
                SELECT 
                    dep.element_id,
                    dep.propertyname,
                    dep.ragtype,
                    dep.description,
                    dep.image_url
                FROM domainelementproperties dep
                WHERE dep.element_id IN ({placeholders})
                ORDER BY dep.element_id, dep.created_at DESC
            ''', element_type_ids)
            properties = cur.fetchall()
            
            # Group properties by element_id (element type id)
            for prop in properties:
                element_id = prop[0]
                if element_id not in element_type_properties:
                    element_type_properties[element_id] = []
                element_type_properties[element_id].append({
                    'propertyname': prop[1],
                    'ragtype': prop[2],
                    'description': prop[3],
                    'image_url': prop[4]
                })
        
        # Get property instances for element occurrences (actual properties assigned to occurrences)
        element_occurrence_ids = [occ['id'] for occ in element_occurrences_context]
        element_occurrence_properties = {}
        if element_occurrence_ids:
            # Get property instances for element occurrences
            placeholders = ','.join(['?' for _ in element_occurrence_ids])
            cur.execute(f'''
                SELECT 
                    cpi.element_instance_id,
                    cpi.instance_name,
                    dep.propertyname,
                    dep.ragtype,
                    dep.description,
                    dep.image_url
                FROM canvas_property_instances cpi
                JOIN domainelementproperties dep ON cpi.property_id = dep.id
                WHERE cpi.element_instance_id IN ({placeholders})
                ORDER BY cpi.element_instance_id, cpi.id
            ''', element_occurrence_ids)
            property_instances = cur.fetchall()
            
            # Group property instances by element_instance_id
            for prop_inst in property_instances:
                element_instance_id = prop_inst[0]
                if element_instance_id not in element_occurrence_properties:
                    element_occurrence_properties[element_instance_id] = []
                element_occurrence_properties[element_instance_id].append({
                    'instance_name': prop_inst[1],
                    'propertyname': prop_inst[2],
                    'ragtype': prop_inst[3],
                    'description': prop_inst[4],
                    'image_url': prop_inst[5]
                })
        
        # Get design rules for context
        cur.execute('''
            SELECT 
                id,
                name,
                description,
                subject_element_type,
                target_element_type,
                relationship_type,
                conditions_json,
                active
            FROM design_rules
            WHERE active = 1
            ORDER BY name
        ''')
        design_rules = cur.fetchall()
        
        # Format design rules for context
        design_rules_context = []
        for rule in design_rules:
            design_rules_context.append({
                'id': rule[0],
                'name': rule[1],
                'description': rule[2],
                'subject_element_type': rule[3],
                'target_element_type': rule[4],
                'relationship_type': rule[5],
                'conditions': json.loads(rule[6]) if rule[6] else None,
                'active': rule[7]
            })
        
        # Get design rule violations for context (Repository Advice)
        cur.execute('''
            SELECT 
                drv.id,
                drv.rule_id,
                dr.name AS rule_name,
                drv.element_instance_id,
                cei.instance_name,
                dm.element AS element_type,
                drv.severity,
                drv.current_value,
                drv.threshold_value
            FROM design_rule_violations drv
            JOIN design_rules dr ON drv.rule_id = dr.id
            LEFT JOIN canvas_element_instances cei ON drv.element_instance_id = cei.id
            LEFT JOIN domainmodel dm ON cei.element_type_id = dm.id
            ORDER BY drv.severity DESC, dr.name
        ''')
        violations = cur.fetchall()
        
        # Format violations for context
        violations_context = []
        for violation in violations:
            violations_context.append({
                'id': violation[0],
                'rule_id': violation[1],
                'rule_name': violation[2],
                'element_instance_id': violation[3],
                'element_instance_name': violation[4],
                'element_type': violation[5],
                'severity': violation[6],  # 'positive', 'warning', or 'negative'
                'current_value': violation[7],
                'threshold_value': violation[8]
            })
        
        cur.close()
        conn.close()
        
        # Combine both for backward compatibility (element_properties keyed by element type id)
        element_properties = element_type_properties
        
        # Generate answer using LLM with properties, design rules, and violations
        # Pass both element types and occurrences separately for better context
        answer, citations = generateEDGYAnswer(
            question,
            element_context,  # Combined for backward compatibility
            relationship_context,
            enterprise_filter=enterprise_filter,
            element_properties=element_properties,  # Properties for element types (templates)
            element_types=element_types_context,  # Element types (definitions)
            element_occurrences=element_occurrences_context,  # Element occurrences (instances)
            element_occurrence_properties=element_occurrence_properties,  # Properties assigned to occurrences
            design_rules=design_rules_context,  # Design rules configuration
            violations=violations_context  # Repository advice (violations)
        )
        
        return jsonify({
            'answer': answer,
            'citations': citations
        })
    except Exception as e:
        if conn:
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500





    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM enterprises WHERE id = ?', (enterprise_id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'message': 'Enterprise definition deleted successfully'}), 200
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

    """
    Extract element names from text that match repository elements.
    Returns a list of element names mentioned in the text.
    Uses word boundaries to avoid partial matches (e.g., "Process" won't match "Processes").
    """
    if not text or not available_elements:
        return []
    
    text_lower = text.lower()
    mentioned = []
    
    # Check each element name to see if it appears in the text
    # Use word boundaries to ensure exact matches
    import re
    for element_name in available_elements:
        if element_name:
            # Create a pattern that matches the element name as a whole word
            # This prevents partial matches (e.g., "Process" won't match "Processes")
            pattern = r'\b' + re.escape(element_name.lower()) + r'\b'
            if re.search(pattern, text_lower):
                mentioned.append(element_name)
    
    return mentioned


def detect_diagram_request(question):
    """
    Detect if the user is requesting a diagram to be created.
    Returns tuple: (is_diagram_request, element_names_list, include_relationships, strict_mode, needs_clarification)
    - include_relationships: True if user explicitly requests relationships, False if only elements requested
    - strict_mode: True if user wants only the specified elements without extending to related elements
    - needs_clarification: True if the request is too vague and needs more specific information
    """
    import re  # Import re for regex pattern matching
    
    if not question:
        return False, [], True, False, False
    
    question_lower = question.lower()
    
    # Keywords that indicate a diagram request
    diagram_keywords = [
        'create a diagram', 'show me a diagram', 'generate a diagram', 'make a diagram',
        'create diagram', 'show diagram', 'generate diagram', 'make diagram',
        'visualize', 'visualise', 'draw a diagram', 'draw diagram',
        'diagram of', 'diagram for', 'diagram with', 'diagram showing',
        'show relationships', 'show me relationships', 'visualize relationships',
        'create a visualization', 'create visualization', 'show me how', 'show how'
    ]
    
    is_diagram_request = any(keyword in question_lower for keyword in diagram_keywords)
    
    # Also treat questions about relationships as diagram requests (e.g., "how X relates to Y")
    if not is_diagram_request and ('relates' in question_lower or 'relate' in question_lower or 'relationship' in question_lower):
        # Check if it's asking about relationships between elements (not just mentioning relationships)
        if re.search(r'\b\w+\s+relates?\s+to\s+\w+', question_lower) or re.search(r'\brelationships?\s+between', question_lower):
            is_diagram_request = True
    
    # Detect if relationships are explicitly requested in diagram context
    # Include relationships if user asks about relationships, relates, or connections
    relationship_keywords = ['with relationship', 'with relationships', 'showing relationship', 'showing relationships',
                            'including relationship', 'including relationships', 'with connection', 'with connections',
                            'with links', 'showing connection', 'showing connections', 'show relationship', 'show relationships',
                            'relates', 'relate', 'relates to', 'related', 'relationship between', 'relationships between']
    include_relationships = any(keyword in question_lower for keyword in relationship_keywords)
    
    # Detect strict mode keywords (only these elements, don't extend)
    strict_keywords = ['only', 'just', 'exactly', 'precisely', 'without extending', 'no other']
    has_strict_keyword = any(keyword in question_lower for keyword in strict_keywords)
    
    # Extract element names from the question
    # Look for patterns like "with Element1, Element2" or "for Element1 and Element2"
    element_names = []
    
    if is_diagram_request:
        # Try to extract element names from common patterns
        import re
        
        # Pattern 1: "with Element1, Element2, Element3"
        with_match = re.search(r'\bwith\s+([^.,!?]+)', question_lower)
        if with_match:
            elements_str = with_match.group(1)
            # Split by comma or "and"
            potential_elements = re.split(r',\s*|\s+and\s+', elements_str)
            element_names.extend([e.strip() for e in potential_elements if e.strip()])
        
        # Pattern 2: "for Element1, Element2"
        for_match = re.search(r'\bfor\s+([^.,!?]+)', question_lower)
        if for_match:
            elements_str = for_match.group(1)
            potential_elements = re.split(r',\s*|\s+and\s+', elements_str)
            element_names.extend([e.strip() for e in potential_elements if e.strip()])
        
        # Pattern 3: "showing Element1, Element2"
        showing_match = re.search(r'\bshowing\s+([^.,!?]+)', question_lower)
        if showing_match:
            elements_str = showing_match.group(1)
            potential_elements = re.split(r',\s*|\s+and\s+', elements_str)
            element_names.extend([e.strip() for e in potential_elements if e.strip()])
        
        # Pattern 4: "of Element1, Element2"
        of_match = re.search(r'\bof\s+([^.,!?]+)', question_lower)
        if of_match:
            elements_str = of_match.group(1)
            potential_elements = re.split(r',\s*|\s+and\s+', elements_str)
            element_names.extend([e.strip() for e in potential_elements if e.strip()])
        
        # Pattern 5: "how X relates to Y" or "X relates to Y" - extract both elements
        relates_match = re.search(r'\bhow\s+([^\s]+)\s+relates?\s+to\s+([^\s,\.!?]+)', question_lower)
        if not relates_match:
            relates_match = re.search(r'\b([^\s]+)\s+relates?\s+to\s+([^\s,\.!?]+)', question_lower)
        if relates_match:
            element_names.extend([relates_match.group(1).strip(), relates_match.group(2).strip()])
        
        # Pattern 6: "relationship between X and Y" or "relationships between X and Y"
        between_match = re.search(r'\brelationships?\s+between\s+([^,\.!?]+)', question_lower)
        if between_match:
            elements_str = between_match.group(1)
            potential_elements = re.split(r'\s+and\s+|\s+,\s*', elements_str)
            element_names.extend([e.strip() for e in potential_elements if e.strip()])
    
    # Clean up element names (remove common words)
    cleaned_names = []
    common_words = {'the', 'a', 'an', 'and', 'or', 'for', 'with', 'showing', 'of', 'all', 'my', 'repository'}
    for name in element_names:
        cleaned = name.strip()
        if cleaned and cleaned.lower() not in common_words and len(cleaned) > 1:
            cleaned_names.append(cleaned)
    
    # Determine strict mode - must be after cleaned_names is defined
    # If asking about relationships between specific elements (e.g., "how X relates to Y"), use strict mode
    # This ensures only the specified elements are shown, not all elements from their facets
    if include_relationships and cleaned_names and len(cleaned_names) >= 2:
        # Asking about relationships between specific elements - use strict mode
        strict_mode = True
    else:
        strict_mode = has_strict_keyword
    
    # Determine if clarification is needed
    # Request is vague if: it's a diagram request but no specific elements mentioned, or only generic terms
    needs_clarification = False
    if is_diagram_request:
        vague_keywords = ['all', 'everything', 'repository', 'all elements', 'all relationships', 'everything in']
        has_vague_keywords = any(keyword in question_lower for keyword in vague_keywords)
        
        # If no specific elements found and request is vague or very generic, need clarification
        if len(cleaned_names) == 0:
            if has_vague_keywords:
                needs_clarification = True
            elif len(question_lower.split()) <= 4:  # Very short requests like "create a diagram"
                needs_clarification = True
    
    return is_diagram_request, cleaned_names, include_relationships, strict_mode, needs_clarification


def detect_open_diagram_request(question):
    """
    Detect if the user is requesting to open/view a saved diagram.
    Returns tuple: (is_open_request, diagram_search_terms)
    - is_open_request: True if user wants to open a saved diagram
    - diagram_search_terms: List of search terms extracted from the question (title keywords, etc.)
    """
    if not question:
        return False, []
    
    question_lower = question.lower()
    
    # Keywords that indicate opening a saved diagram
    open_keywords = [
        'open diagram', 'show diagram', 'view diagram', 'display diagram',
        'open saved diagram', 'show saved diagram', 'view saved diagram', 'display saved diagram',
        'open my diagram', 'show my diagram', 'view my diagram',
        'open the diagram', 'show the diagram', 'view the diagram', 'display the diagram',
        'load diagram', 'load saved diagram'
    ]
    
    is_open_request = any(keyword in question_lower for keyword in open_keywords)
    
    # Extract search terms (diagram title keywords) from the question
    search_terms = []
    if is_open_request:
        # Remove the opening keywords to get potential title keywords
        import re
        for keyword in open_keywords:
            question_lower = question_lower.replace(keyword, '')
        
        # Extract words that might be part of the diagram title
        # Look for quoted strings first (e.g., "My Architecture Diagram")
        quoted_match = re.search(r'["\']([^"\']+)["\']', question)
        if quoted_match:
            search_terms.append(quoted_match.group(1).strip())
        else:
            # Extract remaining significant words (not common stop words)
            words = re.findall(r'\b\w+\b', question_lower)
            stop_words = {'the', 'a', 'an', 'and', 'or', 'for', 'with', 'my', 'saved', 'that', 'called', 'named'}
            search_terms = [w for w in words if len(w) > 2 and w not in stop_words]
    
    return is_open_request, search_terms


def detect_template_diagram_request(question):
    """
    Detect if the user wants to create a diagram using an existing diagram as a template.
    Returns tuple: (is_template_request, template_diagram_name, new_enterprise_filter, new_facet_filter)
    - is_template_request: True if user wants to use a template
    - template_diagram_name: Name/title of the template diagram to use
    - new_enterprise_filter: Enterprise filter for the new diagram (if specified)
    - new_facet_filter: Facet filter for the new diagram (if specified)
    """
    if not question:
        return False, None, None, None
    
    import re
    question_lower = question.lower()
    
    # Keywords that indicate using a template
    template_keywords = [
        'using.*diagram.*as.*template',
        'using.*diagram.*called.*as.*template',
        'using.*diagram.*named.*as.*template',
        'using.*template.*diagram',
        'create.*using.*diagram.*as.*template',
        'create.*based.*on.*diagram',
        'create.*from.*diagram',
        'use.*diagram.*as.*template',
        'template.*diagram'
    ]
    
    is_template_request = False
    template_name = None
    new_enterprise = None
    new_facet = None
    
    # Check for template keywords
    for pattern in template_keywords:
        if re.search(pattern, question_lower):
            is_template_request = True
            break
    
    if is_template_request:
        # Extract template diagram name with improved patterns
        # Pattern 1: "diagram called X" or "diagram named X"
        quoted_match = re.search(r'diagram\s+(?:called|named)\s+["\']?([^"\']+?)["\']?(?:\s+as\s+template|\s+using|$)', question, re.IGNORECASE)
        if quoted_match:
            template_name = quoted_match.group(1).strip()
        else:
            # Pattern 2: Quoted string after "diagram"
            quoted_match = re.search(r'diagram\s+["\']([^"\']+)["\']', question, re.IGNORECASE)
            if quoted_match:
                template_name = quoted_match.group(1).strip()
            else:
                # Pattern 3: Text between "diagram" and "as template" or "using"
                match = re.search(r'diagram\s+(?:called|named)?\s*([^,\.]+?)(?:\s+as\s+template|\s+using|\s+for|$)', question, re.IGNORECASE)
                if match:
                    template_name = match.group(1).strip()
                    # Clean up common words
                    template_name = re.sub(r'\b(the|a|an|in|for|with|using|diagram|template)\b', '', template_name, flags=re.IGNORECASE).strip()
                else:
                    # Pattern 4: Extract text after "using" or "based on" before "diagram"
                    match = re.search(r'(?:using|based\s+on)\s+["\']?([^"\']*?diagram[^"\']*?)["\']?(?:\s+as\s+template|$)', question, re.IGNORECASE)
                    if match:
                        template_name = match.group(1).strip()
                        # Remove "diagram" from the name if it's in the middle
                        template_name = re.sub(r'\bdiagram\b', '', template_name, flags=re.IGNORECASE).strip()
                        template_name = re.sub(r'\s+', ' ', template_name).strip()
        
        # Clean up template name
        if template_name:
            # Remove leading/trailing punctuation
            template_name = re.sub(r'^[^\w]+|[^\w]+$', '', template_name)
            # Normalize whitespace
            template_name = re.sub(r'\s+', ' ', template_name).strip()
            print(f"[Template Detection] Extracted template name: '{template_name}'")
        
        # Extract new enterprise filter (e.g., "elements in 10K1W enterprise")
        enterprise_match = re.search(r'elements?\s+in\s+([a-z0-9]+)\s+enterprise', question_lower)
        if enterprise_match:
            new_enterprise = enterprise_match.group(1).strip()
        else:
            # Try pattern like "for 10K1W enterprise" or "10K1W enterprise"
            enterprise_match = re.search(r'(?:for|in)\s+([a-z0-9]+)\s+enterprise', question_lower)
            if enterprise_match:
                new_enterprise = enterprise_match.group(1).strip()
            else:
                enterprise_match = re.search(r'([a-z0-9]+)\s+enterprise', question_lower)
                if enterprise_match:
                    new_enterprise = enterprise_match.group(1).strip()
        
        # Extract facet filter (e.g., "Architecture elements")
        facet_keywords = ['architecture', 'identity', 'experience', 'base', 'product', 'organisation', 'organization', 'brand']
        for facet in facet_keywords:
            if facet in question_lower:
                new_facet = facet.capitalize()
                break
    
    return is_template_request, template_name, new_enterprise, new_facet













def search_web_for_context(question):
    """
    Search the web for relevant content to enhance chatbot context.
    Uses DuckDuckGo search API (via ddgs library).
    Returns tuple of (formatted_results_string, citations_list) or (None, None) on error.
    """
    try:
        # Try to import ddgs library (formerly duckduckgo_search)
        try:
            from ddgs import DDGS
        except ImportError:
            print("[Web Search] ddgs library not installed. Install with: pip install ddgs")
            return None, None
        
        # Extract key terms from the question for better search
        question_lower = question.lower()
        
        # Build focused search query specifically for Enterprise Design and EDGY content
        # Always include EDGY and Enterprise Design terminology to get relevant results
        
        # Check if question already contains EDGY-specific terms
        edgy_keywords = ['edgy', 'enterprise design', 'facets', 'base facet', 'architecture facet', 
                        'identity facet', 'experience facet', 'capability', 'asset', 'process', 'purpose', 'content', 
                        'story', 'activity', 'outcome', 'object', 'people', 'channel', 'journey', 'task',
                        'product', 'organisation', 'organization', 'brand']
        
        has_edgy_keywords = any(keyword in question_lower for keyword in edgy_keywords)
        
        # Build focused search query with Enterprise Design context
        if has_edgy_keywords:
            # Question already has EDGY terms, reinforce with Enterprise Design context
            search_query = f'"EDGY" "Enterprise Design" {question}'
        else:
            # Question doesn't have EDGY terms, add comprehensive Enterprise Design context
            search_query = f'"EDGY Enterprise Design" framework {question}'
        
        # Additional search terms to improve relevance
        search_query += " -generic -general tutorial guide"
        
        # Perform web search
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(
                    search_query,
                    max_results=5,  # Get more results to filter for Enterprise Design/EDGY relevance
                    region='wt-wt',  # Worldwide
                    safesearch='moderate'
                ))
                
                if results:
                    formatted_results = []
                    citations = []
                    
                    # EDGY and Enterprise Design relevance keywords for filtering
                    relevance_keywords = ['edgy', 'enterprise design', 'enterprise architecture', 
                                         'capability', 'asset', 'process', 'facets', 'facet',
                                         'enterprise modeling', 'business architecture', 'domain model']
                    
                    for i, result in enumerate(results, 1):
                        title = result.get('title', '')
                        body = result.get('body', '')
                        href = result.get('href', '')
                        
                        if title and body:
                            # Calculate relevance score based on EDGY/Enterprise Design keywords
                            title_lower = title.lower()
                            body_lower = body.lower()
                            relevance_score = sum(1 for keyword in relevance_keywords 
                                                if keyword in title_lower or keyword in body_lower)
                            
                            # Only include results with some relevance to Enterprise Design/EDGY
                            # Prioritize results with EDGY or Enterprise Design terms
                            if relevance_score > 0 or 'edgy' in body_lower or 'enterprise design' in body_lower:
                                # Truncate body to 250 characters
                                body_truncated = body[:250] + '...' if len(body) > 250 else body
                                
                                # Format with citation number
                                citation_num = len(citations) + 1
                                formatted_results.append(f"{i}. {title}: {body_truncated} [{citation_num}]")
                                
                                # Store citation with URL
                                if href:
                                    citations.append({
                                        'number': citation_num,
                                        'title': title,
                                        'url': href
                                    })
                                    
                                # Limit to top 3 most relevant results
                                if len(formatted_results) >= 3:
                                    break
                    
                    if formatted_results:
                        # Format citations for display
                        citations_text = "\n\nCitations:\n"
                        for citation in citations:
                            citations_text += f"[{citation['number']}] {citation['title']}\n   {citation['url']}\n"
                        
                        # Combine results with citations
                        full_text = "\n".join(formatted_results) + citations_text
                        return full_text, citations
        except Exception as e:
            print(f"[Web Search] Error performing search: {e}")
            return None, None
        
        return None, None
        
    except Exception as e:
        print(f"[Web Search] Error: {e}")
        return None, None


def normalize_element_type_to_singular(text):
    """
    Normalize plural element type forms to singular for fuzzy matching.
    Returns a dictionary mapping plural forms to singular element types.
    """
    # Mapping of plural forms to singular element types
    plural_to_singular = {
        # Base Facet
        'people': 'people',  # People is already plural
        'activities': 'activity',
        'outcomes': 'outcome',
        'objects': 'object',
        # Architecture Facet
        'capabilities': 'capability',
        'assets': 'asset',
        'processes': 'process',
        # Identity Facet
        'purposes': 'purpose',
        'contents': 'content',
        'stories': 'story',
        # Experience Facet
        'channels': 'channel',
        'journeys': 'journey',
        'journey\'s': 'journey',  # Handle possessive form
        'tasks': 'task',
        # Intersection Elements
        'products': 'product',
        'organisations': 'organisation',
        'organizations': 'organization',
        'brands': 'brand',
    }
    
    # Also handle common irregular plurals and variations
    text_lower = text.lower().strip()
    
    # Check if text matches any plural form
    if text_lower in plural_to_singular:
        return plural_to_singular[text_lower]
    
    # Handle possessive forms (e.g., "Journey's" -> "journey")
    if text_lower.endswith("'s"):
        base = text_lower[:-2]
        if base in plural_to_singular:
            return plural_to_singular[base]
        return base  # Return without possessive
    
    # Handle standard pluralization rules
    # Words ending in 'ies' -> 'y' (e.g., "capabilities" -> "capability")
    if text_lower.endswith('ies'):
        singular = text_lower[:-3] + 'y'
        if singular in ['capability', 'activity']:
            return singular
    
    # Words ending in 'es' -> remove 'es' or 'e' (e.g., "processes" -> "process")
    if text_lower.endswith('es'):
        # Check if removing 'es' gives a valid element type
        without_es = text_lower[:-2]
        if without_es in ['process', 'purpose', 'journey', 'story']:
            return without_es
        # Some words just need 's' removed (e.g., "assets" -> "asset")
        without_s = text_lower[:-1]
        if without_s in ['asset', 'outcome', 'object', 'content', 'channel', 'task']:
            return without_s
    
    # Words ending in 's' -> remove 's' (e.g., "products" -> "product")
    if text_lower.endswith('s') and not text_lower.endswith('ss'):
        without_s = text_lower[:-1]
        if without_s in ['product', 'brand', 'organisation', 'organization', 'people']:
            return without_s
    
    # Return original if no match found
    return text_lower


def generate_fallback_answer(question, elements, relationships, web_context, enterprise_filter=None, element_properties=None):
    """
    Generate an answer from repository data and web search when LLM is unavailable.
    Uses rule-based matching and context extraction.
    """
    # Ensure element_properties is always a dict, never None
    if element_properties is None:
        element_properties = {}
    question_lower = question.lower()
    answer_parts = []
    
    print(f"[Fallback] Processing question: '{question}'")
    print(f"[Fallback] Question (lowercase): '{question_lower}'")
    
    # Add notice that LLM is unavailable
    answer_parts.append("⚠️ **Note: The AI language model is currently unavailable.** I'm providing an answer based on your repository data and web search results.")
    answer_parts.append("")
    
    # Check for enterprise switching requests
    if any(word in question_lower for word in ['switch', 'change', 'show', 'view', 'different enterprise', 'other enterprise']):
        # Get available enterprises
        conn_ent = get_db_connection()
        if conn_ent:
            try:
                cur_ent = conn_ent.cursor()
                cur_ent.execute('SELECT DISTINCT enterprise FROM domainmodel WHERE enterprise IS NOT NULL ORDER BY enterprise')
                available_enterprises = [row[0] for row in cur_ent.fetchall()]
                cur_ent.close()
                conn_ent.close()
                if available_enterprises:
                    answer_parts.append(f"Available enterprises in your repository: {', '.join(available_enterprises)}")
                    if enterprise_filter:
                        answer_parts.append(f"Currently viewing: '{enterprise_filter}'. To switch, select a different enterprise from the dropdown or ask about a specific enterprise.")
                    else:
                        answer_parts.append("Currently viewing all enterprises. To filter by a specific enterprise, select one from the dropdown.")
            except:
                if conn_ent:
                    conn_ent.close()
    
    # EDGY Framework knowledge base
    edgy_facets = {
        "base": {
            "elements": ["People", "Activity", "Outcome", "Object"],
            "relationships": "People perform Activities, use Objects, and achieve Outcomes."
        },
        "architecture": {
            "elements": ["Capability", "Asset", "Process"],
            "relationships": "Capability requires Asset, Process requires Asset, Process realises Capability."
        },
        "identity": {
            "elements": ["Purpose", "Content", "Story"],
            "relationships": "Content expresses Purpose, Content conveys Story, Story contextualises Purpose."
        },
        "experience": {
            "elements": ["Channel", "Journey", "Task"],
            "relationships": "Task is part of Journey, Journey traverses Channel, Task uses Channel."
        },
        "product": {
            "elements": ["Product"],
            "relationships": "Process creates Product, Organisation makes Product, Product features in Journey, Product serves Task, Product embodies Brand."
        },
        "organisation": {
            "elements": ["Organisation"],
            "relationships": "Organisation makes Product, Organisation performs Process."
        },
        "brand": {
            "elements": ["Brand"],
            "relationships": "People perceives Brand, Brand appears in Journey, Product embodies Brand."
        }
    }
    
    # Check for facet-related questions
    for facet_name, facet_info in edgy_facets.items():
        if facet_name in question_lower or any(elem.lower() in question_lower for elem in facet_info["elements"]):
            answer_parts.append(f"The {facet_name.capitalize()} Facet includes: {', '.join(facet_info['elements'])}.")
            answer_parts.append(facet_info["relationships"])
    
    # Special handling for Product relationship questions
    if 'product' in question_lower and ('relationship' in question_lower or 'connect' in question_lower or 'link' in question_lower):
        product_relationships = [
            "Process creates Product",
            "Organisation makes Product", 
            "Product features in Journey",
            "Product serves Task",
            "Product embodies Brand"
        ]
        answer_parts.append("Product has the following relationships in the repository:")
        for rel in product_relationships:
            answer_parts.append(f"  - {rel}")
    
    # Special handling for Organisation relationship questions
    if ('organisation' in question_lower or 'organization' in question_lower) and ('relationship' in question_lower or 'connect' in question_lower or 'link' in question_lower):
        organisation_relationships = [
            "Organisation makes Product",
            "Organisation performs Process"
        ]
        answer_parts.append("Organisation has the following relationships in the repository:")
        for rel in organisation_relationships:
            answer_parts.append(f"  - {rel}")
    
    # Search repository for relevant elements
    matching_elements = []
    question_words = set(question_lower.split())
    
    # Normalize question words to singular forms for fuzzy matching
    normalized_question_words = set()
    for word in question_words:
        normalized = normalize_element_type_to_singular(word)
        normalized_question_words.add(normalized)
        normalized_question_words.add(word)  # Also keep original for exact matches
    
    # CRITICAL: Explicit handling for all element type requests using fuzzy matching
    # Check for both singular and plural forms using normalized words
    # Base Facet
    is_people_request = any(w in ['people'] for w in normalized_question_words) or 'people' in question_lower
    is_activity_request = any(w in ['activity', 'activities'] for w in normalized_question_words) or 'activity' in question_lower or 'activities' in question_lower
    is_outcome_request = any(w in ['outcome', 'outcomes'] for w in normalized_question_words) or 'outcome' in question_lower or 'outcomes' in question_lower
    is_object_request = any(w in ['object', 'objects'] for w in normalized_question_words) or 'object' in question_lower or 'objects' in question_lower
    # Architecture Facet
    is_capability_request = any(w in ['capability', 'capabilities'] for w in normalized_question_words) or 'capability' in question_lower or 'capabilities' in question_lower
    is_asset_request = any(w in ['asset', 'assets'] for w in normalized_question_words) or 'asset' in question_lower or 'assets' in question_lower
    is_process_request = any(w in ['process', 'processes'] for w in normalized_question_words) or 'process' in question_lower or 'processes' in question_lower
    # Identity Facet
    is_purpose_request = any(w in ['purpose', 'purposes'] for w in normalized_question_words) or 'purpose' in question_lower or 'purposes' in question_lower
    is_content_request = any(w in ['content', 'contents'] for w in normalized_question_words) or 'content' in question_lower or 'contents' in question_lower
    is_story_request = any(w in ['story', 'stories'] for w in normalized_question_words) or 'story' in question_lower or 'stories' in question_lower
    # Experience Facet
    is_channel_request = any(w in ['channel', 'channels'] for w in normalized_question_words) or 'channel' in question_lower or 'channels' in question_lower
    is_journey_request = any(w in ['journey', 'journeys', 'journey\'s'] for w in normalized_question_words) or 'journey' in question_lower or 'journeys' in question_lower or 'journey\'s' in question_lower
    is_task_request = any(w in ['task', 'tasks'] for w in normalized_question_words) or 'task' in question_lower or 'tasks' in question_lower
    # Intersection Elements
    is_product_request = any(w in ['product', 'products'] for w in normalized_question_words) or 'product' in question_lower or 'products' in question_lower
    is_organisation_request = any(w in ['organisation', 'organization', 'organisations', 'organizations'] for w in normalized_question_words) or ('organisation' in question_lower or 'organization' in question_lower or 
                              'organisations' in question_lower or 'organizations' in question_lower)
    is_brand_request = any(w in ['brand', 'brands'] for w in normalized_question_words) or 'brand' in question_lower or 'brands' in question_lower
    
    for elem in elements:
        # Elements now include: id, name, element, facet, enterprise, description, image_url (if available)
        element_id = elem[0]
        name = elem[1]
        element_type = elem[2]
        facet = elem[3]
        enterprise = elem[4]
        description = elem[5] if len(elem) > 5 else ""
        image_url = elem[6] if len(elem) > 6 else None
        name_lower = name.lower()
        elem_lower = (element_type.lower().strip() if element_type else "")
        facet_lower = (facet.lower().strip() if facet else "")
        
        # CRITICAL: Explicit matching for all element types using fuzzy matching
        # Check if this element matches the requested element type (case-insensitive)
        # Normalize element type to singular for comparison
        elem_type_normalized = normalize_element_type_to_singular(elem_lower)
        element_type_match = False
        
        # Check each element type request independently (not mutually exclusive)
        # Base Facet
        if is_people_request and elem_type_normalized == 'people':
            element_type_match = True
        if is_activity_request and elem_type_normalized == 'activity':
            element_type_match = True
        if is_outcome_request and elem_type_normalized == 'outcome':
            element_type_match = True
        if is_object_request and elem_type_normalized == 'object':
            element_type_match = True
        # Architecture Facet
        if is_capability_request and elem_type_normalized == 'capability':
            element_type_match = True
        if is_asset_request and elem_type_normalized == 'asset':
            element_type_match = True
        if is_process_request and elem_type_normalized == 'process':
            element_type_match = True
        # Identity Facet
        if is_purpose_request and elem_type_normalized == 'purpose':
            element_type_match = True
        if is_content_request and elem_type_normalized == 'content':
            element_type_match = True
        if is_story_request and elem_type_normalized == 'story':
            element_type_match = True
        # Experience Facet
        if is_channel_request and elem_type_normalized == 'channel':
            element_type_match = True
        if is_journey_request and elem_type_normalized == 'journey':
            element_type_match = True
        if is_task_request and elem_type_normalized == 'task':
            element_type_match = True
        # Intersection Elements
        if is_product_request and elem_type_normalized == 'product':
            element_type_match = True
            print(f"[Fallback] Matched Product element: {name} (element_type: {element_type})")
        if is_organisation_request and elem_type_normalized in ['organisation', 'organization']:
            element_type_match = True
            print(f"[Fallback] Matched Organisation element: {name} (element_type: {element_type})")
        if is_brand_request and elem_type_normalized == 'brand':
            element_type_match = True
            print(f"[Fallback] Matched Brand element: {name} (element_type: {element_type})")
        
        # General matching: check if question mentions this element by name, type, or facet
        # Use normalized words for fuzzy matching
        general_match = False
        if any(word in name_lower or word in elem_lower or word in facet_lower or 
               normalize_element_type_to_singular(word) in elem_lower or 
               normalize_element_type_to_singular(word) == elem_type_normalized
               for word in normalized_question_words if len(word) > 3):
            general_match = True
        
        # Include element if it matches explicitly by type OR matches generally
        # CRITICAL: Also check enterprise filter if specified
        # For Product, Organisation, and Brand elements, they may have NULL enterprise, so include them regardless
        enterprise_match = True
        if enterprise_filter:
            # If enterprise filter is set, element must match enterprise OR be Product/Organisation/Brand
            if enterprise and enterprise.strip():
                enterprise_match = enterprise.lower().strip() == enterprise_filter.lower().strip()
            else:
                # Element has no enterprise - only include if it's Product/Organisation/Brand
                enterprise_match = elem_lower in ['product', 'organisation', 'organization', 'brand']
        
        if (element_type_match or general_match) and enterprise_match:
            matching_elements.append((element_id, name, element_type, facet, enterprise, description, image_url))
    
    # Search relationships for relevant connections
    matching_relationships = []
    for rel in relationships:
        # Relationship format: (source_element_id, source_element_name, target_element_id, target_element_name, relationship_type)
        # Convert to strings to handle integers/None values
        source_name = str(rel[1] or "") if len(rel) > 1 else ""
        rel_type = str(rel[4] or "") if len(rel) > 4 else ""
        target_name = str(rel[3] or "") if len(rel) > 3 else ""
        rel_desc = ""  # Description not in the relationship query
        
        # Enhanced matching: check source, target, relationship type, and description
        source_lower = source_name.lower() if source_name else ""
        target_lower = target_name.lower() if target_name else ""
        rel_type_lower = rel_type.lower() if rel_type else ""
        rel_desc_lower = rel_desc.lower() if rel_desc else ""
        
        # Match if any question word appears in source, target, relationship type, or description
        if any(word in source_lower or word in target_lower or word in rel_type_lower or word in rel_desc_lower
               for word in question_words if len(word) > 3):
            matching_relationships.append(rel)
        
        # Also match Product-related relationships when Product is mentioned
        if 'product' in question_lower:
            if source_lower == 'product' or target_lower == 'product':
                if rel not in matching_relationships:
                    matching_relationships.append(rel)
    
    # Build answer from repository data with detailed element information including properties
    # ALWAYS present repository content in a table format - build complete HTML as single string
    
    # Check if an element type was explicitly requested but no matches found for the enterprise
    is_explicit_element_type_request = (is_people_request or is_activity_request or is_outcome_request or 
                                         is_object_request or is_capability_request or is_asset_request or 
                                         is_process_request or is_purpose_request or is_content_request or 
                                         is_story_request or is_channel_request or is_journey_request or 
                                         is_task_request or is_product_request or is_organisation_request or 
                                         is_brand_request)
    
    if is_explicit_element_type_request and not matching_elements and enterprise_filter:
        # Determine which element type was requested
        requested_element_type = None
        if is_people_request:
            requested_element_type = "People"
        elif is_activity_request:
            requested_element_type = "Activity"
        elif is_outcome_request:
            requested_element_type = "Outcome"
        elif is_object_request:
            requested_element_type = "Object"
        elif is_capability_request:
            requested_element_type = "Capability"
        elif is_asset_request:
            requested_element_type = "Asset"
        elif is_process_request:
            requested_element_type = "Process"
        elif is_purpose_request:
            requested_element_type = "Purpose"
        elif is_content_request:
            requested_element_type = "Content"
        elif is_story_request:
            requested_element_type = "Story"
        elif is_channel_request:
            requested_element_type = "Channel"
        elif is_journey_request:
            requested_element_type = "Journey"
        elif is_task_request:
            requested_element_type = "Task"
        elif is_product_request:
            requested_element_type = "Product"
        elif is_organisation_request:
            requested_element_type = "Organisation"
        elif is_brand_request:
            requested_element_type = "Brand"
        
        # Check what element types DO exist for this enterprise
        enterprise_element_types = set()
        for elem in elements:
            elem_enterprise = (elem[4] or "").strip() if len(elem) > 4 else ""
            elem_type = (elem[2] or "").strip() if len(elem) > 2 else ""
            # Include elements matching enterprise OR Product/Organisation/Brand (which may have NULL enterprise)
            if enterprise_filter:
                if elem_enterprise and elem_enterprise.lower() == enterprise_filter.lower():
                    if elem_type:
                        enterprise_element_types.add(elem_type)
                elif elem_type.lower() in ['product', 'organisation', 'organization', 'brand']:
                    # Include intersection elements even if they don't have enterprise
                    enterprise_element_types.add(elem_type)
            else:
                if elem_type:
                    enterprise_element_types.add(elem_type)
        
        # Build helpful fallback message
        answer_parts.append(f"\n**No {requested_element_type} elements found for '{enterprise_filter}'**")
        answer_parts.append("")
        answer_parts.append(f"I couldn't find any **{requested_element_type}** elements in your repository for the enterprise **'{enterprise_filter}'**.")
        answer_parts.append("")
        
        if enterprise_element_types:
            # Show what element types ARE available for this enterprise
            sorted_types = sorted(enterprise_element_types)
            if len(sorted_types) == 1:
                answer_parts.append(f"The repository contains **{sorted_types[0]}** elements for '{enterprise_filter}'.")
            else:
                types_list = ", ".join([f"**{t}**" for t in sorted_types[:-1]]) + f", and **{sorted_types[-1]}**"
                answer_parts.append(f"The repository contains {types_list} elements for '{enterprise_filter}'.")
            answer_parts.append("")
            answer_parts.append("You can:")
            answer_parts.append(f"- Ask to see other element types for '{enterprise_filter}'")
            answer_parts.append(f"- Check if {requested_element_type} elements exist for other enterprises")
            answer_parts.append(f"- Add new {requested_element_type} elements to the repository")
        else:
            # No elements at all for this enterprise
            answer_parts.append(f"The repository doesn't contain any elements for the enterprise '{enterprise_filter}'.")
            answer_parts.append("")
            answer_parts.append("You can:")
            answer_parts.append("- Check other enterprises in the repository")
            answer_parts.append(f"- Add elements to the '{enterprise_filter}' enterprise")
        
        # Return early since we've provided the fallback message
        return "\n".join(answer_parts)
    
    try:
        if matching_elements:
            answer_parts.append("\n### Relevant Elements in Your Repository\n")
            
            for elem in matching_elements[:10]:  # Limit to 10
                element_id = elem[0]
                name = elem[1]
                element_type = elem[2]
                facet = elem[3]
                enterprise = elem[4]
                description = elem[5] if len(elem) > 5 and elem[5] is not None else ""
                
                # Use element type for image reference, not instance name
                element_type_for_image = element_type if element_type else 'Unknown'
                
                # Format element information as text
                answer_parts.append(f"\n**{name}**")
                answer_parts.append(f"[ELEMENT_IMAGE:{element_type_for_image}]")
                answer_parts.append(f"*Type:* {element_type or '-'} | *Facet:* {facet or 'Base'} | *Enterprise:* {enterprise or '-'}")
                
                if description and isinstance(description, str) and len(description) > 0:
                    desc_display = description[:200] + "..." if len(description) > 200 else description
                    answer_parts.append(f"*Description:* {desc_display}")
                
                # Add properties if available
                if element_properties and element_id in element_properties:
                    props = element_properties[element_id]
                    if props:
                        answer_parts.append(f"*Properties ({len(props)}):*")
                        for prop in props[:5]:  # Limit to 5 properties
                            prop_name = prop.get('propertyname') or 'Unnamed Property'
                            prop_ragtype = prop.get('ragtype') or '-'
                            prop_description = prop.get('description') or ''
                            
                            # Use RAG type for property image
                            rag_type_for_image = prop_ragtype if prop_ragtype and prop_ragtype != '-' else 'Green'
                            answer_parts.append(f"  - [PROPERTY_IMAGE:{rag_type_for_image}] **{prop_name}** ({prop_ragtype})")
                            if prop_description:
                                prop_desc_short = prop_description[:100] + "..." if len(prop_description) > 100 else prop_description
                                answer_parts.append(f"    *{prop_desc_short}*")
                
                answer_parts.append("")  # Empty line between elements
                
    except Exception as table_error:
        import traceback
        table_trace = traceback.format_exc()
        print(f"[Fallback Answer] Error generating formatted text: {str(table_error)}")
        print(f"[Fallback Answer] Traceback:\n{table_trace}")
        # Continue without formatted elements - add elements as simple list instead
        if matching_elements:
            answer_parts.append("\n**Relevant elements in your repository:**")
            for elem in matching_elements[:5]:
                element_id = elem[0]
                name = elem[1]
                element_type = elem[2]
                facet = elem[3]
                enterprise = elem[4]
                description = elem[5] if len(elem) > 5 else ""
                element_type_for_image = element_type if element_type else 'Unknown'
                answer_parts.append(f"- **{name}** [ELEMENT_IMAGE:{element_type_for_image}] *({element_type})* - {facet or 'Base'} Facet")
                if description:
                    answer_parts.append(f"  *{description[:100]}*")
    
    if matching_relationships:
        answer_parts.append("\nRelevant relationships in your repository:")
        for rel in matching_relationships[:10]:  # Limit to 10 to show more relationships
            source, rel_type, target = rel[0], rel[1], rel[2]
            rel_desc = rel[3] if len(rel) > 3 else ""
            rel_info = f"- {source} {rel_type} {target}"
            if rel_desc:
                rel_info += f" ({rel_desc[:100]})"  # Include description snippet
            answer_parts.append(rel_info)
    
    # Add general repository summary if no specific matches
    if not matching_elements and not matching_relationships:
        if elements:
            answer_parts.append(f"\nYour repository contains {len(elements)} elements:")
            for elem in elements[:10]:  # Show first 10
                # Elements now include: id, name, element, facet, enterprise, description, image_url (if available)
                name = elem[1]
                element_type = elem[2]
                facet = elem[3]
                image_url = elem[6] if len(elem) > 6 else None
                elem_info = f"- {name}"
                if image_url:
                    elem_info += f" [ELEMENT_IMAGE:{name}]"
                elem_info += f" ({element_type}) - {facet} Facet" if facet else f" ({element_type}) - Base Facet"
                answer_parts.append(elem_info)
            if len(elements) > 10:
                answer_parts.append(f"... and {len(elements) - 10} more elements.")
        
        if relationships:
            answer_parts.append(f"\nYour repository has {len(relationships)} relationships defined.")
    
    # Add web search results if available (already includes citations)
    if web_context:
        answer_parts.append("\n\n📚 Additional information from web search:")
        answer_parts.append(web_context)
    elif not matching_elements and not matching_relationships:
        # If no repository matches and no web context, provide helpful message
        answer_parts.append("\n\n💡 Tip: Try asking about specific elements, relationships, or EDGY concepts. You can also check your repository data directly.")
    
    # Handle common question patterns
    if "what" in question_lower or "tell me about" in question_lower:
        if not answer_parts:
            answer_parts.append("Based on the available information, I can help you understand your repository structure and EDGY concepts.")
    
    if "how many" in question_lower:
        if "element" in question_lower:
            answer_parts.insert(0, f"Your repository contains {len(elements)} elements.")
        elif "relationship" in question_lower:
            answer_parts.insert(0, f"Your repository contains {len(relationships)} relationships.")
    
    # Combine all parts with error handling
    try:
        if answer_parts:
            response = "\n".join(answer_parts)
            # Ensure response is a valid string
            if not isinstance(response, str):
                response = str(response)
            # Ensure response is not empty
            if not response or len(response.strip()) == 0:
                response = "I couldn't find specific information to answer your question. Please try rephrasing or asking about specific elements or relationships in your repository."
            response += "\n\n(Note: This answer was generated from repository data and web search. The LLM service is currently unavailable.)"
            return response
        else:
            return "I can access your repository data and web search, but couldn't find specific information to answer your question. " \
                   "Please try rephrasing your question or check if the relevant elements/relationships exist in your repository."
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[Fallback Answer] Error combining answer parts: {str(e)}")
        print(f"[Fallback Answer] Traceback:\n{error_trace}")
        # Return a basic response with repository info
        response = f"⚠️ **Note: The AI language model is currently unavailable.**\n\n"
        if elements:
            response += f"Your repository contains {len(elements)} elements."
        if relationships:
            response += f"\nYour repository has {len(relationships)} relationships."
        if not response.strip():
            response = "I encountered an error processing your question. Please try again."
        response += "\n\n(Note: This answer was generated from repository data. The LLM service is currently unavailable.)"
        return response


def generateEDGYAnswer(question, elements, relationships, enterprise_filter=None, element_properties=None, element_types=None, element_occurrences=None, element_occurrence_properties=None, design_rules=None, violations=None):
    """Generate answer using Gemini LLM based on EDGY knowledge, repository data, and web content
    
    Args:
        question: User's question
        elements: Combined list of element types and occurrences (for backward compatibility)
        relationships: List of relationships
        enterprise_filter: Optional enterprise filter
        element_properties: Dictionary of properties by element type id (templates/definitions)
        element_types: List of element types (definitions from domainmodel)
        element_occurrences: List of element occurrences (instances from canvas_element_instances)
        element_occurrence_properties: Dictionary of property instances by element occurrence id
        design_rules: List of design rules configuration
        violations: List of design rule violations (Repository Advice)
    """
    
    # Ensure element_properties is always a dict, never None
    if element_properties is None:
        element_properties = {}
    
    # Check if there's any data to work with
    has_data = len(elements) > 0 or len(relationships) > 0
    
    # If enterprise filter is set but no data exists, return early with helpful message
    if enterprise_filter:
        if len(elements) == 0 and len(relationships) == 0:
            return (f"I don't have any elements or relationships in the repository for the '{enterprise_filter}' enterprise. Please select a different enterprise or add data for this enterprise.", [])
        elif len(elements) == 0:
            return (f"I don't have any elements in the repository for the '{enterprise_filter}' enterprise. Please add elements for this enterprise or select a different enterprise.", [])
        elif len(relationships) == 0:
            return (f"I don't have any relationships in the repository for the '{enterprise_filter}' enterprise. Please add relationships for this enterprise or select a different enterprise.", [])
    
    # Get list of all available enterprises for context
    conn_for_enterprises = get_db_connection()
    available_enterprises = []
    if conn_for_enterprises:
        try:
            cur_ent = conn_for_enterprises.cursor()
            cur_ent.execute('SELECT DISTINCT enterprise FROM domainmodel WHERE enterprise IS NOT NULL ORDER BY enterprise')
            available_enterprises = [row[0] for row in cur_ent.fetchall()]
            cur_ent.close()
            conn_for_enterprises.close()
        except:
            if conn_for_enterprises:
                conn_for_enterprises.close()
    
    # Build context for Gemini with detailed element information
    context_parts = []
    
    # Add enterprise context and available enterprises
    if enterprise_filter:
        context_parts.append(f"Current Enterprise Filter: '{enterprise_filter}'")
        context_parts.append(f"CRITICAL: An enterprise filter is currently active: '{enterprise_filter}'. When responding to element type requests (e.g., 'show me Product elements', 'show me Organisation elements', 'show me Brand elements'), you MUST maintain this filter and ONLY include elements that belong to the '{enterprise_filter}' enterprise. Exception: Product, Organisation, and Brand elements with no enterprise value (NULL) may be included as they are intersection elements that span enterprises. For all other element types, ONLY include elements that have the matching enterprise value.")
    else:
        context_parts.append("Current Enterprise Filter: None (showing all enterprises)")
    
    if available_enterprises:
        context_parts.append(f"Available Enterprises in Repository: {', '.join(available_enterprises)}")
        context_parts.append("The user can switch between enterprises by mentioning the enterprise name or asking to view a different enterprise.")
    
    # Add detailed repository context with element types and occurrences separately
    # First, add Element Types (definitions)
    if element_types:
        context_parts.append(f"\n=== Element Types (Definitions) ===")
        context_parts.append(f"The repository has {len(element_types)} element type definitions. These are the available element types that can be used to create element occurrences.")
        context_parts.append("CRITICAL: When users ask about 'element types', 'available elements', or 'what elements are available', refer to this section.")
        
        # Group element types by facet
        element_types_by_facet = {}
        for elem_type in element_types:
            if isinstance(elem_type, dict):
                element_type = elem_type.get('element_type', '')
                facet = elem_type.get('facet', '')
                name = elem_type.get('name', '')
                enterprise = elem_type.get('enterprise', '')
                description = elem_type.get('description', '')
                image_url = elem_type.get('image_url')
            else:
                element_type = elem_type[2] if len(elem_type) > 2 else ""
                facet = elem_type[3] if len(elem_type) > 3 else ""
                name = elem_type[1] if len(elem_type) > 1 else ""
                enterprise = elem_type[4] if len(elem_type) > 4 else ""
                description = elem_type[5] if len(elem_type) > 5 else ""
                image_url = elem_type[6] if len(elem_type) > 6 else None
            
            # Determine facet name
            element_type_lower = (element_type.lower().strip() if element_type else "")
            if element_type_lower == "brand":
                facet_name = "Brand"
            elif element_type_lower == "product":
                facet_name = "Product"
            elif element_type_lower in ["organisation", "organization"]:
                facet_name = "Organisation"
            else:
                facet_name = facet or "Base"
            
            if facet_name not in element_types_by_facet:
                element_types_by_facet[facet_name] = []
            
            element_types_by_facet[facet_name].append({
                'name': name,
                'element_type': element_type,
                'enterprise': enterprise,
                'description': description,
                'image_url': image_url
            })
        
        # Format element types by facet
        for facet_name, facet_types in element_types_by_facet.items():
            context_parts.append(f"\n{facet_name} Facet - Element Types ({len(facet_types)} types):")
            for elem_type in facet_types:
                type_info = f"  - {elem_type['name']} (Type: {elem_type['element_type']})"
                if elem_type.get('enterprise'):
                    type_info += f" [Enterprise: {elem_type['enterprise']}]"
                if elem_type.get('description'):
                    type_info += f"\n    Description: {elem_type['description']}"
                context_parts.append(type_info)
    
    # Then, add Element Occurrences (instances)
    if element_occurrences:
        context_parts.append(f"\n=== Element Occurrences (Instances) ===")
        context_parts.append(f"The repository has {len(element_occurrences)} element occurrences. These are actual instances of element types that have been created in models.")
        context_parts.append("CRITICAL: When users ask about 'element occurrences', 'instances', 'how many [element type] instances', or 'show me [element type] instances', refer to this section.")
        
        # Ensure element_occurrence_properties is a dict
        if element_occurrence_properties is None:
            element_occurrence_properties = {}
        
        # Group occurrences by element type
        occurrences_by_type = {}
        for occurrence in element_occurrences:
            if isinstance(occurrence, dict):
                occurrence_id = occurrence.get('id')
                element_type = occurrence.get('element_type', '')
                name = occurrence.get('name', '')
                type_name = occurrence.get('type_name', '')
                facet = occurrence.get('facet', '')
                enterprise = occurrence.get('enterprise', '')
                description = occurrence.get('description', '')
                image_url = occurrence.get('image_url')
                model_name = occurrence.get('model_name')
            else:
                occurrence_id = occurrence[0] if len(occurrence) > 0 else None
                element_type = occurrence[4] if len(occurrence) > 4 else ""
                name = occurrence[1] if len(occurrence) > 1 else ""
                type_name = occurrence[3] if len(occurrence) > 3 else ""
                facet = occurrence[5] if len(occurrence) > 5 else ""
                enterprise = occurrence[6] if len(occurrence) > 6 else ""
                description = occurrence[7] if len(occurrence) > 7 else ""
                image_url = occurrence[8] if len(occurrence) > 8 else None
                model_name = occurrence[9] if len(occurrence) > 9 else None
            
            if element_type not in occurrences_by_type:
                occurrences_by_type[element_type] = []
            
            # Get properties for this occurrence
            properties = element_occurrence_properties.get(occurrence_id, []) if occurrence_id else []
            
            occurrences_by_type[element_type].append({
                'id': occurrence_id,
                'name': name,
                'type_name': type_name,
                'facet': facet,
                'enterprise': enterprise,
                'description': description,
                'image_url': image_url,
                'model_name': model_name,
                'properties': properties
            })
        
        # Format occurrences by element type
        for element_type, occurrences in occurrences_by_type.items():
            context_parts.append(f"\n{element_type} Occurrences ({len(occurrences)} instances):")
            for occ in occurrences:
                occ_info = f"  - {occ['name']} (Instance of: {occ['type_name']})"
                if occ.get('model_name'):
                    occ_info += f" [Model: {occ['model_name']}]"
                if occ.get('enterprise'):
                    occ_info += f" [Enterprise: {occ['enterprise']}]"
                if occ.get('description'):
                    occ_info += f"\n    Description: {occ['description']}"
                
                # Add properties information
                if occ.get('properties') and len(occ['properties']) > 0:
                    occ_info += f"\n    Properties ({len(occ['properties'])} assigned):"
                    for prop in occ['properties']:
                        prop_name = prop.get('instance_name') or prop.get('propertyname') or 'Unnamed Property'
                        prop_info = f"      - {prop_name}"
                        if prop.get('ragtype'):
                            prop_info += f" [RAG: {prop['ragtype']}]"
                        if prop.get('description'):
                            prop_info += f" - {prop['description']}"
                        if prop.get('image_url'):
                            prop_info += f" [PROPERTY_IMAGE:{prop['image_url']}]"
                        occ_info += f"\n{prop_info}"
                
                context_parts.append(occ_info)
    
    # Legacy support: also include combined elements for backward compatibility
    if elements and not element_types and not element_occurrences:
        context_parts.append(f"\nRepository Elements ({len(elements)} total):")
        
        # Group elements by facet for better organization
        elements_by_facet = {}
        for e in elements:
            # Elements are dictionaries with keys: id, name, element_type, facet, enterprise, description, image_url
            # Handle both dictionary and tuple formats for backward compatibility
            if isinstance(e, dict):
                element_id = e.get('id')
                name = e.get('name', '')
                element_type = e.get('element_type', '')
                facet = e.get('facet', '')
                enterprise = e.get('enterprise', '')
                description = e.get('description', '')
                image_url = e.get('image_url')
            else:
                # Fallback for tuple format (legacy support)
                element_id = e[0] if len(e) > 0 else None
                name = e[1] if len(e) > 1 else ""
                element_type = e[2] if len(e) > 2 else ""
                facet = e[3] if len(e) > 3 else ""
                enterprise = e[4] if len(e) > 4 else ""
                description = e[5] if len(e) > 5 else ""
                image_url = e[6] if len(e) > 6 else None
            # CRITICAL: For Brand, Product, and Organisation elements, use their element type as facet name
            # This matches how they're handled in generate_plantuml_code
            element_type_lower = (element_type.lower().strip() if element_type else "")
            if element_type_lower == "brand":
                facet_name = "Brand"
            elif element_type_lower == "product":
                facet_name = "Product"
            elif element_type_lower in ["organisation", "organization"]:
                facet_name = "Organisation"
            else:
                facet_name = facet or "Base"
            
            if facet_name not in elements_by_facet:
                elements_by_facet[facet_name] = []
            
            # Get properties for this element
            properties = []
            if element_properties is not None and element_id in element_properties:
                properties = element_properties[element_id]
                if properties:
                    print(f"[Chat Debug] Element '{name}' (ID: {element_id}) has {len(properties)} properties")
            
            elements_by_facet[facet_name].append({
                'name': name,
                'element_type': element_type,  # This is the element type field (e.g., 'brand', 'organisation', 'product', 'people', 'capability', etc.)
                'enterprise': enterprise,
                'description': description,
                'image_url': image_url,
                'properties': properties
            })
        
        # Format elements by facet with descriptions and properties
        for facet_name, facet_elements in elements_by_facet.items():
            context_parts.append(f"\n{facet_name} Facet ({len(facet_elements)} elements):")
            for elem in facet_elements:
                elem_info = f"  - {elem['name']}"
                # Add element image reference for ChatBot to use in responses
                if elem.get('image_url'):
                    elem_info += f" [ELEMENT_IMAGE:{elem['name']}] [Image URL: {elem['image_url']}]"
                if elem['element_type']:
                    # CRITICAL: Explicitly show element type, especially for Brand, Organisation, Product
                    elem_type_display = elem['element_type'].lower().strip()
                    elem_info += f" (Element Type: {elem['element_type']})"
                    # Add explicit note for intersection elements - check both British and American spellings
                    # IMPORTANT: These are stored with capital letters in the database (e.g., 'Organisation', 'Product', 'Brand')
                    if elem_type_display in ['brand', 'organisation', 'organization', 'product']:
                        elem_info += f" [ELEMENT TYPE: {elem['element_type']} - This is an ELEMENT in the repository, treat it like any other element type (People, Activity, Capability, etc.)]"
                        # Extra emphasis for Product and Organisation since they're not showing
                        if elem_type_display in ['product', 'organisation', 'organization']:
                            elem_info += f" [CRITICAL: When user asks for '{elem['element_type']} elements', you MUST include this element in your response]"
                if elem['enterprise']:
                    elem_info += f" [Enterprise: {elem['enterprise']}]"
                if elem['description']:
                    elem_info += f"\n    Description: {elem['description']}"
                
                # Add properties information
                if elem.get('properties') and len(elem['properties']) > 0:
                    elem_info += f"\n    Properties ({len(elem['properties'])}):"
                    for prop in elem['properties']:
                        prop_name = prop.get('propertyname') or 'Unnamed Property'
                        prop_image_url = prop.get('image_url')
                        prop_info = f"      - {prop_name}"
                        # Add property image reference if available (for ChatBot to use in responses)
                        if prop_image_url:
                            prop_info += f" [Image URL: {prop_image_url}] [PROPERTY_IMAGE:{prop_image_url}]"
                        if prop.get('ragtype'):
                            prop_info += f" [RAG: {prop['ragtype']}]"
                        if prop.get('description'):
                            prop_info += f" - {prop['description']}"
                        elem_info += f"\n{prop_info}"
                
                context_parts.append(elem_info)
    
    # Add detailed relationship context - include ALL relationships for better understanding
    # This ensures the chatbot is aware of every relationship in the repository
    if relationships:
        context_parts.append(f"\nRepository Relationships ({len(relationships)} total - ALL relationships in repository):")
        context_parts.append("These are ALL the relationships that exist in the repository. Use these when answering questions about connections between elements.")
        # Include all relationships to ensure chatbot understands all connections
        # Relationship format: dictionaries with keys: source_id, source_name, target_id, target_name, type
        # Handle both dictionary and tuple formats for backward compatibility
        for r in relationships:
            if isinstance(r, dict):
                source_name = str(r.get('source_name', ''))
                rel_type = str(r.get('type', ''))
                target_name = str(r.get('target_name', ''))
            else:
                # Fallback for tuple format (legacy support)
                source_name = str(r[1] or "") if len(r) > 1 else ""
                rel_type = str(r[4] or "") if len(r) > 4 else ""
                target_name = str(r[3] or "") if len(r) > 3 else ""
            rel_desc = ""  # Description not in the relationship query
            rel_info = f"  - {source_name} --[{rel_type}]--> {target_name}"
            if rel_desc:
                rel_info += f"\n    Description: {rel_desc[:200]}"  # Truncate long descriptions
            context_parts.append(rel_info)
    
    # Add Design Rules context
    if design_rules:
        context_parts.append(f"\n=== Design Rules Configuration ===")
        context_parts.append(f"The repository has {len(design_rules)} active design rules. These rules define quality standards and best practices for element relationships.")
        for rule in design_rules:
            rule_info = f"  - Rule: {rule.get('name', 'Unnamed Rule')}"
            if rule.get('description'):
                rule_info += f"\n    Description: {rule['description']}"
            rule_info += f"\n    Subject Element: {rule.get('subject_element_type', 'N/A')}"
            if rule.get('target_element_type'):
                rule_info += f" → Target Element: {rule['target_element_type']}"
            if rule.get('relationship_type'):
                rule_info += f" (Relationship: {rule['relationship_type']})"
            context_parts.append(rule_info)
    
    # Add Repository Advice (Design Rule Violations) context
    if violations:
        context_parts.append(f"\n=== Repository Advice (Design Rule Violations) ===")
        context_parts.append(f"The repository has {len(violations)} design rule violations. These indicate areas where elements may not meet design quality standards.")
        
        # Group violations by severity
        violations_by_severity = {'positive': [], 'warning': [], 'negative': []}
        for violation in violations:
            severity = violation.get('severity', 'warning')
            if severity in violations_by_severity:
                violations_by_severity[severity].append(violation)
        
        for severity in ['negative', 'warning', 'positive']:
            severity_violations = violations_by_severity[severity]
            if severity_violations:
                severity_label = severity.capitalize()
                context_parts.append(f"\n{severity_label} Violations ({len(severity_violations)}):")
                for violation in severity_violations[:10]:  # Limit to first 10 per severity
                    violation_info = f"  - Rule: {violation.get('rule_name', 'Unknown Rule')}"
                    if violation.get('element_instance_name'):
                        violation_info += f" | Element: {violation['element_instance_name']}"
                    if violation.get('element_type'):
                        violation_info += f" (Type: {violation['element_type']})"
                    violation_info += f" | Current: {violation.get('current_value', 'N/A')} | Threshold: {violation.get('threshold_value', 'N/A')}"
                    context_parts.append(violation_info)
                if len(severity_violations) > 10:
                    context_parts.append(f"    ... and {len(severity_violations) - 10} more {severity} violations")
    
    context = "\n".join(context_parts) if context_parts else "No repository data available."
    
    # Debug: Check if properties are in context
    if element_properties is not None:
        props_count = sum(len(props) for props in element_properties.values()) if element_properties else 0
        props_in_context = sum(1 for part in context_parts if 'Properties (' in part)
        print(f"[Chat Debug] Total properties in dict: {props_count}, Properties sections in context: {props_in_context}")
    
    # Get web search results for additional context (always get it for fallback)
    web_context, web_citations = search_web_for_context(question)
    
    # Build prompt for Gemini
    prompt_parts = [
        "You are an EDGY Enterprise Design assistant. Answer the user's question about their repository and EDGY concepts.",
        "",
        "CRITICAL FORMATTING RULE:",
        "When presenting repository elements, use formatted text with headings, bold, and italic styling.",
        "DO NOT use HTML tables. Instead, format elements as follows:",
        "- Use **bold** for element names",
        "- Use *italic* for element types and facets",
        "- Use headings (## or ###) for section headers",
        "- Use [ELEMENT_IMAGE:element_type] for element images (e.g., [ELEMENT_IMAGE:People], [ELEMENT_IMAGE:Capability])",
        "- Use [PROPERTY_IMAGE:rag_type] for property images (e.g., [PROPERTY_IMAGE:Red], [PROPERTY_IMAGE:Green])",
        "- Keep font size small and readable",
        "- Use clear, concise formatting with proper spacing",
        "",
        "EDGY Framework Knowledge:",
        "- Base Facet: People, Activity, Outcome, Object. People perform Activities, use Objects, and achieve Outcomes.",
        "- Architecture Facet: Capability, Asset, Process. Capability requires Asset, Process requires Asset, Process realises Capability.",
        "- Identity Facet: Purpose, Content, Story. Content expresses Purpose, Content conveys Story, Story contextualises Purpose.",
        "- Experience Facet: Channel, Journey, Task. Task is part of Journey, Journey traverses Channel, Task uses Channel.",
        "- Product (Intersection Element): Process creates Product, Organisation makes Product, Product features in Journey, Product serves Task, Product embodies Brand.",
        "- Organisation (Intersection Element): Organisation makes Product, Organisation performs Process.",
        "- Brand (Intersection Element): People perceives Brand, Brand appears in Journey, Product embodies Brand.",
        "",
        "CRITICAL: Brand, Organisation, and Product are ELEMENTS in the repository, just like any other element type.",
        "When users ask for Brand elements, Organisation elements (or Organization elements), or Product elements, you MUST include them in your response.",
        "These intersection elements are stored in the repository with element types that may be capitalized: 'Brand'/'brand', 'Organisation'/'Organisation'/'organization'/'Organization', and 'Product'/'product'.",
        "The element type field in the repository may use capital letters (e.g., 'Organisation', 'Product', 'Brand') - always check case-insensitively when searching.",
        "Treat them exactly like any other element type (People, Activity, Capability, etc.) when responding to user queries.",
        "",
        "IMPORTANT: The Repository Context below contains ALL elements and ALL relationships in the user's repository.",
        "You MUST use the actual relationships listed in 'Repository Relationships' when answering questions.",
        "Do NOT rely solely on the general EDGY framework knowledge above - always reference the specific repository data.",
        "",
        "Repository Context:",
        context,
    ]
    
    # Add web context if available
    if web_context:
        prompt_parts.extend([
            "",
            "Additional Web Context:",
            web_context,
        ])
    
    prompt_parts.extend([
        "",
        f"User Question: {question}",
        "",
        "Instructions:",
        "1. Answer ONLY what the user asked. Be direct and concise. Do not add extra information unless specifically requested.",
        "2. Use exact element names from the repository when referencing elements.",
        "3. When discussing relationships, use ONLY the relationships listed in 'Repository Relationships' above. The system is aware of ALL relationships in the repository.",
        "4. For diagram requests: Acknowledge briefly (e.g., 'I'll create a diagram with [elements]'). Never generate diagram code - the system handles this automatically.",
        "5. For vague diagram requests, ask for clarification: which specific elements, whether to include relationships, and scope.",
        "6. For element images, use format [ELEMENT_IMAGE:element_type] where element_type is the element type (e.g., People, Capability, Process). The system will map these to standard images in the /images folder.",
        "7. For property images (RAG tags), use format [PROPERTY_IMAGE:rag_type] where rag_type is the RAG type (e.g., Red, Yellow, Green, Black). The system will map these to standard images in the /images folder.",
        "8. The diagram generation system has access to ALL elements and ALL relationships in the repository - it will use the appropriate ones based on the user's request.",
        "9. CRITICAL: When presenting ANY repository elements in your response, use formatted text with headings, bold, and italic styling. DO NOT use HTML tables. Format elements clearly with proper headings and styling.",
        "10. For template diagram requests: When a user asks to create a diagram 'using diagram X as template' or 'based on diagram Y', use the EXACT template diagram title from the 'Available Template Diagrams' list above. If the user's template name doesn't match exactly, suggest the closest match from the available templates list.",
        "11. CRITICAL: Brand, Organisation (or Organization), and Product are ELEMENTS. When users ask for 'Brand elements', 'Organisation elements' (or 'Organization elements'), or 'Product elements', you MUST search the repository for elements where the element type field matches (case-insensitive): 'Brand'/'brand', 'Organisation'/'Organisation'/'organization'/'Organization', or 'Product'/'product' respectively, and include ALL matching elements in your response. Do NOT exclude these elements or treat them differently from other element types. The element type field may be stored with capital letters (e.g., 'Organisation', 'Product', 'Brand') - always check case-insensitively. Example: If a user asks 'show me Organisation elements', look for elements where element_type is 'Organisation' OR 'organisation' OR 'Organization' OR 'organization' - they are all the same element type.",
        "12. CRITICAL FOR PRODUCT AND ORGANISATION: Product and Organisation elements are stored in the repository exactly like Brand elements. When a user asks 'show me Product elements' or 'show me Organisation elements', you MUST find ALL elements where the element_type field (shown as 'Element Type: Product' or 'Element Type: Organisation' in the repository context) matches the request, and display them using formatted text with headings and styling. Do NOT skip Product or Organisation elements - they are regular elements just like Brand, People, Activity, Capability, etc. If you see elements with 'Element Type: Product' or 'Element Type: Organisation' in the repository context, you MUST include them when requested.",
        "13. CRITICAL: ENTERPRISE FILTER MAINTENANCE: When an enterprise filter is active (indicated by 'Current Enterprise Filter: X' at the beginning of the Repository Context), you MUST maintain this filter in your responses. If a user requests elements of a specific type (e.g., 'show me Product elements', 'show me Organisation elements', 'show me Brand elements'), you MUST ONLY include elements that match BOTH the requested element type AND the active enterprise filter. Elements without an enterprise value (NULL) should only be included if they are Product, Organisation, or Brand elements (intersection elements that span enterprises). For all other element types, ONLY include elements that have the matching enterprise value. Example: If enterprise filter is '10K1W' and user asks for 'Product elements', show ONLY Product elements where Enterprise is '10K1W' OR Product elements with no enterprise value (NULL).",
        "14. CRITICAL: PLURAL FORMS: Users may ask for elements using plural forms (e.g., 'Capabilities', 'Processes', 'Assets', 'Journeys', 'Stories', 'Purposes', 'Tasks', 'Organisations', etc.). You MUST understand these as requests for the singular element type. For example: 'Capabilities' means 'Capability' elements, 'Processes' means 'Process' elements, 'Assets' means 'Asset' elements, 'Journeys' or 'Journey's' means 'Journey' elements, 'Stories' means 'Story' elements, 'Purposes' means 'Purpose' elements, 'Tasks' means 'Task' elements, 'Organisations' or 'Organizations' means 'Organisation'/'Organization' elements, 'Products' means 'Product' elements, 'Brands' means 'Brand' elements, 'Activities' means 'Activity' elements, 'Outcomes' means 'Outcome' elements, 'Objects' means 'Object' elements, 'Channels' means 'Channel' elements, 'Contents' means 'Content' elements. Always match plural forms to their singular element types when searching the repository.",
        "15. CRITICAL: NO ELEMENTS FOUND FOR ENTERPRISE: If a user requests elements of a specific type (e.g., 'show me Capability elements', 'show me Process elements') for a specific enterprise, and NO elements of that type exist in the repository for that enterprise, you MUST provide a helpful fallback message. The message should: (1) Clearly state that no [Element Type] elements were found for '[Enterprise Name]', (2) List what element types ARE available for that enterprise (if any), (3) Suggest actions the user can take (e.g., check other enterprises, add elements, etc.). Format this message clearly and helpfully. Do NOT return an empty table or say 'no results found' without context. Example: 'No Capability elements found for '10K1W'. The repository contains Process, Asset, and People elements for '10K1W'. You can ask to see other element types for '10K1W', check if Capability elements exist for other enterprises, or add new Capability elements to the repository.'",
        "16. ELEMENT TYPES vs ELEMENT OCCURRENCES: CRITICAL DISTINCTION - The repository has two separate concepts: (1) Element Types (definitions from domainmodel table) - these are the available element type definitions like 'People', 'Capability', 'Process', etc. (2) Element Occurrences (instances from canvas_element_instances table) - these are actual instances of element types that have been created in models, like 'John Doe' (instance of People type) or 'Customer Service Capability' (instance of Capability type). When users ask about 'element types', 'available elements', or 'what elements are available', refer to Element Types. When users ask about 'element occurrences', 'instances', 'how many [element type] instances', 'show me [element type] instances', or 'count of [element type]', refer to Element Occurrences. Always distinguish between these two concepts in your responses.",
        "17. PROPERTIES: CRITICAL - There are two types of properties: (1) Property Templates/Definitions - These are property definitions associated with Element Types (shown in the Element Types section). These define what properties are available for an element type. (2) Property Instances - These are actual properties assigned to Element Occurrences (shown in the Element Occurrences section under each occurrence). Property instances are the actual properties that have been assigned to specific element occurrences. When users ask 'What properties does [Element Occurrence] have?', 'How many properties are assigned to [Element Occurrence]?', or 'Show me occurrences with properties', refer to Property Instances in the Element Occurrences section. When users ask 'What properties are available for [Element Type]?', refer to Property Templates in the Element Types section. Always distinguish between property templates (definitions) and property instances (assigned properties).",
        "18. MODELS: When users ask about 'models', 'diagrams', 'saved diagrams', or 'model structure', they may be referring to saved diagram models in the repository. Acknowledge that models/diagrams are stored representations of element arrangements. If specific model information is requested, explain what models typically contain (elements, relationships, layout) based on EDGY principles.",
        "19. ENTERPRISE DESIGN INSIGHTS: When users ask for insights, analysis, patterns, or recommendations about their Enterprise Design, provide thoughtful analysis based on the repository data. Look for patterns in element distribution across facets, relationship patterns, property distributions, enterprise coverage, and alignment with EDGY framework principles. Provide actionable insights such as: missing element types, relationship gaps, property status trends, facet balance, and enterprise design maturity indicators.",
        "20. DESIGN RULES: When users ask about 'design rules', 'rules', 'quality rules', or 'design standards', refer to the Design Rules Configuration section. Design rules define quality standards for element relationships (e.g., 'Process elements should have at least 2 Asset relationships'). Explain what rules are configured, their thresholds, and what they measure.",
        "21. REPOSITORY ADVICE: When users ask about 'repository advice', 'violations', 'design rule violations', 'advice', 'warnings', or 'quality issues', refer to the Repository Advice (Design Rule Violations) section. Violations indicate where elements may not meet design quality standards. Negative violations are critical issues, warning violations are concerns, and positive violations indicate good practices. Provide specific information about violations including which elements are affected, what rules they violate, and current vs threshold values."
    ])
    
    prompt = "\n".join(prompt_parts)
    
    # Call Gemini LLM with sufficient tokens to avoid truncation
    # Reduced from 8192 to 4096 for better reliability and to prevent truncation issues
    # The simplified instructions should help prevent confusion and ensure complete responses
    max_tokens = 4096
    answer = call_gemini(prompt, max_tokens=max_tokens)
    
    # Handle quota errors and failures - use fallback
    if answer in ["QUOTA_EXCEEDED", "QUOTA_RATE_LIMIT", "QUOTA_ERROR"] or not answer:
        # Use fallback answer generator with web search and repository data
        print(f"[Chatbot] LLM unavailable ({answer if answer else 'no response'}), using fallback with web search and repository data")
        fallback_answer = generate_fallback_answer(question, elements, relationships, web_context, enterprise_filter, element_properties)
        return (fallback_answer, [])
    elif answer:
        # Clean answer: Remove any diagram code blocks (PlantUML, Mermaid, etc.)
        import re
        # Remove PlantUML code blocks
        answer = re.sub(r'```plantuml.*?```', '', answer, flags=re.DOTALL | re.IGNORECASE)
        answer = re.sub(r'@startuml.*?@enduml', '', answer, flags=re.DOTALL | re.IGNORECASE)
        # Remove Mermaid code blocks
        answer = re.sub(r'```mermaid.*?```', '', answer, flags=re.DOTALL | re.IGNORECASE)
        # Remove any code blocks that might contain diagram syntax
        answer = re.sub(r'```.*?```', '', answer, flags=re.DOTALL)
        # Remove standalone PlantUML directives
        answer = re.sub(r'!include\s+<[^>]+>', '', answer, flags=re.IGNORECASE)
        answer = re.sub(r'!theme\s+\w+', '', answer, flags=re.IGNORECASE)
        # Clean up extra whitespace
        answer = re.sub(r'\n{3,}', '\n\n', answer)
        answer = answer.strip()
        
        # Remove any HTML tables from the answer and ensure formatted text only
        import re
        # Remove any remaining HTML tables
        answer = re.sub(r'<table[^>]*>[\s\S]*?</table>', '', answer, flags=re.IGNORECASE)
        
        # Return answer and citations separately (citations not included in answer string)
        return (answer, web_citations if web_citations else [])
    else:
        # Final fallback - LLM returned empty or invalid response
        print(f"[Chatbot] LLM returned empty response, using fallback with web search and repository data")
        fallback_answer = generate_fallback_answer(question, elements, relationships, web_context, enterprise_filter, element_properties)
        return (fallback_answer, [])

# Properties endpoints
@app.route('/api/properties', methods=['GET'])
def get_all_properties():
    """Get all properties across all elements (for selection when creating new elements)"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT DISTINCT 
                dep.propertyname,
                dep.ragtype,
                dep.description,
                dep.image_url,
                COUNT(*) as usage_count
            FROM domainelementproperties dep
            WHERE dep.propertyname IS NOT NULL
            GROUP BY dep.propertyname, dep.ragtype, dep.description, dep.image_url
            ORDER BY dep.propertyname, usage_count DESC
        ''')
        columns = [desc[0] for desc in cur.description]
        properties = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify(properties)
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500


@app.route('/api/properties/manage', methods=['GET'])
def get_properties_for_management():
    """Get properties with IDs for management (create/edit/delete)."""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT 
                dep.id,
                dep.element_id,
                dep.propertyname,
                dep.ragtype,
                dep.description,
                dep.image_url,
                dep.created_at,
                dep.updated_at,
                CASE 
                    WHEN dep.element_id IS NULL AND dr.id IS NOT NULL THEN 1
                    ELSE 0
                END AS is_rules_generated,
                dr.id AS rule_id
            FROM domainelementproperties dep
            LEFT JOIN design_rules dr ON LOWER(dr.name) = LOWER(dep.propertyname)
            WHERE dep.propertyname IS NOT NULL
            ORDER BY dep.propertyname, dep.id
        ''')
        columns = [desc[0] for desc in cur.description]
        properties = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify(properties)
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/properties', methods=['POST'])
def create_property():
    """Create a new property"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        propertyname = data.get('propertyname')
        ragtype = data.get('ragtype', '')
        description = data.get('description', '')
        image_url = data.get('image_url', '')
        
        if not propertyname:
            return jsonify({'error': 'Property name is required'}), 400
        
        cur = conn.cursor()
        
        # element_id is optional - properties can be template properties (NULL) or element-specific
        element_id = data.get('element_id')
        
        # Ensure element_id is None (not empty string or 0) if not provided
        if element_id is None or element_id == '' or element_id == 0:
            element_id = None
        
        # Insert new property (element_id can be NULL for template properties)
        # Explicitly use None for NULL values
        cur.execute('''
            INSERT INTO domainelementproperties (element_id, propertyname, ragtype, description, image_url)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            None if element_id is None else element_id,
            propertyname if propertyname else None,
            ragtype if ragtype else None,
            description if description else None,
            image_url if image_url else None
        ))
        
        conn.commit()
        property_id = cur.lastrowid
        
        cur.close()
        conn.close()
        
        return jsonify({
            'id': property_id,
            'propertyname': propertyname,
            'ragtype': ragtype,
            'description': description,
            'image_url': image_url,
            'message': 'Property created successfully'
        }), 201
        
    except sqlite3.IntegrityError as e:
        if conn:
            conn.rollback()
            conn.close()
        import traceback
        traceback.print_exc()
        error_msg = str(e)
        print(f"[Property Creation Error] IntegrityError: {error_msg}")
        print(f"[Property Creation Error] Data received: propertyname={propertyname}, ragtype={ragtype}, element_id={element_id}")
        return jsonify({'error': f'Property already exists or database error: {error_msg}'}), 400
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        import traceback
        traceback.print_exc()
        error_msg = str(e)
        print(f"[Property Creation Error] Exception: {error_msg}")
        print(f"[Property Creation Error] Data received: propertyname={propertyname}, ragtype={ragtype}, element_id={element_id}")
        return jsonify({'error': error_msg}), 500

@app.route('/api/properties', methods=['PUT'])
def update_property():
    """Update an existing property"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Original property identifiers
        old_propertyname = data.get('old_propertyname')
        old_ragtype = data.get('old_ragtype', '')
        old_description = data.get('old_description', '')
        old_image_url = data.get('old_image_url', '')
        
        # New property values
        new_propertyname = data.get('propertyname')
        new_ragtype = data.get('ragtype', '')
        new_description = data.get('description', '')
        new_image_url = data.get('image_url', '')
        
        if not old_propertyname or not new_propertyname:
            return jsonify({'error': 'Property name is required'}), 400
        
        cur = conn.cursor()
        
        # Find all matching properties
        cur.execute('''
            SELECT id FROM domainelementproperties
            WHERE propertyname = ? 
            AND (ragtype = ? OR (? = '' AND ragtype IS NULL))
            AND (description = ? OR (? = '' AND description IS NULL))
            AND (image_url = ? OR (? = '' AND image_url IS NULL))
        ''', (old_propertyname, old_ragtype, old_ragtype, old_description, old_description, old_image_url, old_image_url))
        
        property_ids = [row[0] for row in cur.fetchall()]
        
        if not property_ids:
            cur.close()
            conn.close()
            return jsonify({'error': 'Property not found'}), 404
        
        # Update all matching properties
        # Determine new image_url based on ragtype if not provided
        if not new_image_url and new_ragtype:
            new_image_url = f'/images/Tag-{new_ragtype}.svg'
        
        placeholders = ','.join(['?'] * len(property_ids))
        cur.execute(f'''
            UPDATE domainelementproperties
            SET propertyname = ?,
                ragtype = ?,
                description = ?,
                image_url = ?
            WHERE id IN ({placeholders})
        ''', (new_propertyname, new_ragtype if new_ragtype else None, 
              new_description if new_description else None,
              new_image_url if new_image_url else None) + tuple(property_ids))
        
        updated_count = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'message': f'Property updated successfully. {updated_count} record(s) updated.',
            'updated_count': updated_count
        }), 200
        
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/properties', methods=['DELETE'])
def delete_property():
    """Delete a property from being available for new assignments, but keep historical uses"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.json
        propertyname = data.get('propertyname')
        ragtype = data.get('ragtype', '')
        description = data.get('description', '')
        image_url = data.get('image_url', '')
        
        if not propertyname:
            return jsonify({'error': 'Property name is required'}), 400
        
        cur = conn.cursor()
        
        # Check if property is used in canvas_property_instances (historical uses)
        # We'll delete from domainelementproperties but keep canvas_property_instances
        # First, get all property IDs that match this property
        cur.execute('''
            SELECT id FROM domainelementproperties
            WHERE propertyname = ? 
            AND (ragtype = ? OR (? = '' AND ragtype IS NULL))
            AND (description = ? OR (? = '' AND description IS NULL))
            AND (image_url = ? OR (? = '' AND image_url IS NULL))
        ''', (propertyname, ragtype, ragtype, description, description, image_url, image_url))
        
        property_ids = [row[0] for row in cur.fetchall()]
        
        if not property_ids:
            cur.close()
            conn.close()
            return jsonify({'error': 'Property not found'}), 404
        
        # Check if any of these properties are used in canvas_property_instances
        # We'll still delete from domainelementproperties, but we need to handle the foreign key
        # Since canvas_property_instances references domainelementproperties(id),
        # we need to either:
        # 1. Delete the foreign key constraint temporarily (not recommended)
        # 2. Set property_id to NULL in canvas_property_instances (but this breaks references)
        # 3. Keep the records but mark them as deleted (soft delete)
        # 
        # Actually, looking at the requirement: "keep any historical uses of it against existing Element Instances"
        # This means we should keep canvas_property_instances intact. But the foreign key will prevent deletion.
        # 
        # Best approach: Delete from domainelementproperties where NOT referenced by canvas_property_instances
        # For those that ARE referenced, we'll keep them but they won't appear in the available properties list
        # because we'll filter them out in the GET endpoint
        
        # Actually, simpler approach: Delete all matching records from domainelementproperties
        # The foreign key constraint will prevent deletion if referenced, so we'll catch that error
        # and handle it gracefully
        
        # Check if any of these properties are used in canvas_property_instances
        if property_ids:
            placeholders = ','.join(['?'] * len(property_ids))
            cur.execute(f'''
                SELECT COUNT(*) FROM canvas_property_instances
                WHERE property_id IN ({placeholders})
            ''', property_ids)
            in_use_count = cur.fetchone()[0]
            
            if in_use_count > 0:
                # Property is in use - we can't delete due to foreign key constraint
                # Instead, we'll delete only properties that are NOT referenced
                # This way, historical uses are preserved
                cur.execute('''
                    DELETE FROM domainelementproperties
                    WHERE propertyname = ? 
                    AND (ragtype = ? OR (? = '' AND ragtype IS NULL))
                    AND (description = ? OR (? = '' AND description IS NULL))
                    AND (image_url = ? OR (? = '' AND image_url IS NULL))
                    AND id NOT IN (
                        SELECT DISTINCT property_id 
                        FROM canvas_property_instances 
                        WHERE property_id IS NOT NULL
                    )
                ''', (propertyname, ragtype, ragtype, description, description, image_url, image_url))
                
                deleted_count = cur.rowcount
                conn.commit()
                cur.close()
                conn.close()
                
                if deleted_count == 0:
                    return jsonify({
                        'error': 'Cannot delete property: All instances are currently in use on the canvas. Historical uses are preserved.',
                        'in_use': True
                    }), 409
                
                return jsonify({
                    'message': f'Property deleted successfully. {deleted_count} record(s) removed. Some instances are preserved due to canvas usage.',
                    'deleted_count': deleted_count,
                    'preserved_count': in_use_count
                }), 200
        
        # No references found - safe to delete all
        cur.execute('''
            DELETE FROM domainelementproperties
            WHERE propertyname = ? 
            AND (ragtype = ? OR (? = '' AND ragtype IS NULL))
            AND (description = ? OR (? = '' AND description IS NULL))
            AND (image_url = ? OR (? = '' AND image_url IS NULL))
        ''', (propertyname, ragtype, ragtype, description, description, image_url, image_url))
        
        deleted_count = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        
        if deleted_count == 0:
            return jsonify({'error': 'Property not found'}), 404
        
        return jsonify({
            'message': f'Property deleted successfully. {deleted_count} record(s) removed.',
            'deleted_count': deleted_count
        }), 200
            
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': str(e)}), 500

# Element Properties endpoints
@app.route('/api/elements/<int:element_id>/properties', methods=['GET'])
def get_element_properties(element_id):
    """Get all properties for a specific element"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT id, element_id, ragtype, propertyname, description, image_url, created_at, updated_at
            FROM domainelementproperties
            WHERE element_id = ?
            ORDER BY created_at DESC
        ''', (element_id,))
        columns = [desc[0] for desc in cur.description]
        properties = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify(properties)
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/properties/templates', methods=['GET'])
def get_property_templates():
    """Get available property templates"""
    templates = {
        'risk-assessment': [
            {'propertyname': 'Risk Level', 'ragtype': 'Warning', 'description': 'Overall risk assessment level'},
            {'propertyname': 'Risk Category', 'ragtype': '', 'description': 'Category of risk'},
            {'propertyname': 'Mitigation Status', 'ragtype': '', 'description': 'Current mitigation status'}
        ],
        'compliance': [
            {'propertyname': 'Compliance Status', 'ragtype': 'Positive', 'description': 'Current compliance status'},
            {'propertyname': 'Regulatory Framework', 'ragtype': '', 'description': 'Applicable regulatory framework'},
            {'propertyname': 'Last Audit Date', 'ragtype': '', 'description': 'Date of last compliance audit'},
            {'propertyname': 'Next Review Date', 'ragtype': 'Warning', 'description': 'Scheduled next review date'}
        ],
        'performance': [
            {'propertyname': 'Performance Score', 'ragtype': 'Positive', 'description': 'Overall performance score'},
            {'propertyname': 'Response Time', 'ragtype': '', 'description': 'Average response time'},
            {'propertyname': 'Throughput', 'ragtype': '', 'description': 'Throughput metrics'},
            {'propertyname': 'Availability', 'ragtype': 'Positive', 'description': 'Availability percentage'}
        ],
        'maturity': [
            {'propertyname': 'Maturity Level', 'ragtype': '', 'description': 'Current maturity level'},
            {'propertyname': 'Capability Score', 'ragtype': 'Positive', 'description': 'Capability maturity score'},
            {'propertyname': 'Improvement Areas', 'ragtype': 'Warning', 'description': 'Areas requiring improvement'}
        ]
    }
    return jsonify(templates)


@app.route('/api/elements/<int:element_id>/properties', methods=['POST'])
def add_element_property(element_id):
    """Add a new property to an element"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.json
        ragtype = data.get('ragtype')
        image_url = data.get('image_url')
        
        # Automatically set image URL based on RAG type if not provided
        if not image_url and ragtype:
            ragtype_lower = ragtype.lower().strip()
            if ragtype_lower == 'negative' or ragtype_lower.startswith('negative') or ragtype_lower == 'red' or ragtype_lower.startswith('red'):
                image_url = '/images/Tag-Red.svg'
            elif ragtype_lower == 'warning' or ragtype_lower.startswith('warning') or ragtype_lower == 'amber' or ragtype_lower == 'yellow' or ragtype_lower.startswith('amber') or ragtype_lower.startswith('yellow'):
                image_url = '/images/Tag-Yellow.svg'
            elif ragtype_lower == 'positive' or ragtype_lower.startswith('positive') or ragtype_lower == 'green' or ragtype_lower.startswith('green'):
                image_url = '/images/Tag-Green.svg'
            elif ragtype_lower == 'black' or ragtype_lower.startswith('black'):
                image_url = '/images/Tag-Black.svg'
        
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO domainelementproperties (element_id, ragtype, propertyname, description, image_url, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ''', (
            element_id,
            ragtype,
            data.get('propertyname'),
            data.get('description'),
            image_url
        ))
        conn.commit()
        property_id = cur.lastrowid
        cur.execute('SELECT * FROM domainelementproperties WHERE id = ?', (property_id,))
        columns = [desc[0] for desc in cur.description]
        property_record = dict(zip(columns, cur.fetchone()))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify(property_record), 201
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/elements/with-yellow-properties', methods=['GET'])
def get_elements_with_yellow_properties():
    """Get all elements that have properties with yellow/amber RAG type"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        enterprise_filter = request.args.get('enterprise')
        cur = conn.cursor()
        
        # Query to get elements that have at least one property with yellow/amber RAG type
        query = '''
            SELECT DISTINCT 
                dm.id, 
                dm.name, 
                dm.description, 
                dm.enterprise, 
                dm.facet, 
                dm.element, 
                dm.image_url,
                dm.created_at,
                dm.updated_at
            FROM domainmodel dm
            INNER JOIN domainelementproperties dep ON dm.id = dep.element_id
            WHERE LOWER(TRIM(dep.ragtype)) IN ('yellow', 'amber')
            OR LOWER(TRIM(dep.ragtype)) LIKE 'yellow%'
            OR LOWER(TRIM(dep.ragtype)) LIKE 'amber%'
        '''
        
        params = []
        if enterprise_filter and enterprise_filter.strip() != '' and enterprise_filter.lower() != 'all':
            query += ' AND dm.enterprise = ?'
            params.append(enterprise_filter)
        
        query += ' ORDER BY dm.name'
        
        cur.execute(query, params)
        columns = [desc[0] for desc in cur.description]
        elements = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify(elements)
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/elements/<int:element_id>/properties/<int:property_id>', methods=['DELETE'])
def delete_element_property(element_id, property_id):
    """Delete a property from an element"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('''
            DELETE FROM domainelementproperties
            WHERE id = ? AND element_id = ?
            RETURNING *
        ''', (property_id, element_id))
        result = cur.fetchone()
        if not result:
            cur.close()
            conn.close()
            return jsonify({'error': 'Property not found'}), 404
        
        columns = [desc[0] for desc in cur.description]
        property_record = dict(zip(columns, result))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'message': 'Property deleted successfully', 'property': property_record})
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

# PlantUML Diagram storage endpoints
@app.route('/api/diagrams', methods=['POST'])
def save_diagram():
    """Save a PlantUML diagram with its elements.
    Validates that all element_ids belong to the specified enterprise_filter (repository).
    """
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.json
        plantuml_code = data.get('plantuml_code')
        title = data.get('title')
        enterprise_filter = data.get('enterprise_filter')
        encoded = data.get('encoded')  # Raw encoded string (preferred)
        encoded_url_param = data.get('encoded_url')  # May be full URL or encoded string
        elements_count = data.get('elements_count', 0)
        relationships_count = data.get('relationships_count', 0)
        element_ids = data.get('element_ids', [])  # List of element IDs in the diagram
        
        # Validate repository scoping: ensure all element_ids belong to the enterprise_filter
        if element_ids and enterprise_filter:
            cur_validate = conn.cursor()
            # Check if all elements belong to the specified enterprise
            placeholders = ','.join(['?'] * len(element_ids))
            cur_validate.execute(f'''
                SELECT id, enterprise, name
                FROM domainmodel
                WHERE id IN ({placeholders})
            ''', element_ids)
            
            elements_data = cur_validate.fetchall()
            invalid_elements = []
            for elem in elements_data:
                elem_id, elem_enterprise, elem_name = elem
                if (elem_enterprise or "").lower() != enterprise_filter.lower():
                    invalid_elements.append(f"{elem_name} (ID: {elem_id})")
            
            cur_validate.close()
            
            if invalid_elements:
                return jsonify({
                    'error': f'Repository scoping violation: The following elements do not belong to repository "{enterprise_filter}": {", ".join(invalid_elements)}'
                }), 400
        
        # If encoded is provided, use it; otherwise try to extract from encoded_url
        if not encoded and encoded_url_param:
            # Extract encoded string from URL if it's a full URL
            if 'plantuml.com' in str(encoded_url_param):
                import re
                match = re.search(r'plantuml/[^/]+/~?1?([^/\?]+)', str(encoded_url_param))
                if match:
                    encoded = match.group(1)
                    # Remove ~1 prefix if present
                    if encoded.startswith('~1'):
                        encoded = encoded[2:]
            else:
                # Assume it's already the encoded string
                encoded = encoded_url_param
        
        # Store the raw encoded string in encoded_url field (not the full URL)
        # This makes it easier to retrieve and use
        encoded_for_storage = encoded or ''
        
        if not plantuml_code:
            return jsonify({'error': 'PlantUML code is required'}), 400
        
        cur = conn.cursor()
        
        # Insert diagram
        # Store the raw encoded string in encoded_url field (we'll use it as the encoded value)
        cur.execute('''
            INSERT INTO plantumldiagrams (plantuml_code, title, enterprise_filter, encoded_url, elements_count, relationships_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ''', (plantuml_code, title, enterprise_filter, encoded_for_storage, elements_count, relationships_count))
        conn.commit()
        diagram_id = cur.lastrowid
        cur.execute('SELECT * FROM plantumldiagrams WHERE id = ?', (diagram_id,))
        columns = [desc[0] for desc in cur.description]
        diagram = dict(zip(columns, cur.fetchone()))
        
        # Insert element references
        for element_id in element_ids:
            cur.execute('''
                INSERT OR IGNORE INTO plantumldiagram_elements (diagram_id, element_id, created_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (diagram_id, element_id))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify(diagram), 201
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/diagrams', methods=['GET'])
def get_diagrams():
    """Get all saved diagrams (excludes plantuml_code to improve performance)"""
    conn = None
    cur = None
    try:
        print(f"[Diagrams] Loading saved diagrams...")
        conn = get_db_connection()
        if not conn:
            print("[Diagrams] ERROR: Database connection failed")
            return jsonify({'error': 'Database connection failed'}), 500
        
        enterprise_filter = request.args.get('enterprise')
        cur = conn.cursor()
        
        # Timeout already set in get_db_connection, but ensure it's set here too
        # conn.execute('PRAGMA busy_timeout = 10000')  # Already set in get_db_connection
        
        if enterprise_filter:
            print(f"[Diagrams] Filtering by enterprise: {enterprise_filter}")
            cur.execute('''
                SELECT id, title, enterprise_filter, encoded_url, elements_count, relationships_count, created_at, updated_at
                FROM plantumldiagrams
                WHERE enterprise_filter = ?
                ORDER BY created_at DESC
            ''', (enterprise_filter,))
        else:
            print("[Diagrams] Loading all diagrams (no enterprise filter)")
            cur.execute('''
                SELECT id, title, enterprise_filter, encoded_url, elements_count, relationships_count, created_at, updated_at
                FROM plantumldiagrams
                ORDER BY created_at DESC
            ''')
        
        columns = [desc[0] for desc in cur.description]
        print(f"[Diagrams] Fetching rows...")
        rows = cur.fetchall()
        print(f"[Diagrams] Fetched {len(rows)} rows, converting to dicts...")
        
        diagrams = []
        for idx, row in enumerate(rows):
            try:
                diagram_dict = dict(zip(columns, row))
                diagrams.append(diagram_dict)
                if idx < 3:  # Log first few for debugging
                    print(f"[Diagrams] Sample diagram {idx}: id={diagram_dict.get('id')}, title={diagram_dict.get('title')[:50] if diagram_dict.get('title') else 'None'}")
            except Exception as e:
                print(f"[Diagrams] Error converting row {idx} to dict: {e}")
                import traceback
                traceback.print_exc()
        
        print(f"[Diagrams] Successfully loaded {len(diagrams)} diagrams")
        
        cur.close()
        conn.close()
        print(f"[Diagrams] Connection closed, preparing JSON response...")
        
        # Test JSON serialization before returning
        try:
            import json as json_lib
            test_json = json_lib.dumps(diagrams)
            print(f"[Diagrams] JSON serialization successful, size: {len(test_json)} bytes")
        except Exception as json_error:
            print(f"[Diagrams] ERROR: JSON serialization failed: {json_error}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Failed to serialize diagrams: {str(json_error)}'}), 500
        
        print(f"[Diagrams] Returning JSON response with {len(diagrams)} diagrams")
        response = jsonify(diagrams)
        print(f"[Diagrams] Response created, sending...")
        return response
    except Exception as e:
        print(f"[Diagrams] ERROR loading diagrams: {str(e)}")
        import traceback
        traceback.print_exc()
        if cur:
            try:
                cur.close()
            except:
                pass
        if conn:
            try:
                conn.close()
            except:
                pass
        return jsonify({'error': f'Failed to load diagrams: {str(e)}'}), 500

@app.route('/api/diagrams/<int:diagram_id>', methods=['GET'])
def get_diagram(diagram_id):
    """Get a specific diagram with its elements.
    Optionally validates that the diagram belongs to the specified enterprise/repository.
    """
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        # Optional enterprise filter for repository scoping validation
        enterprise_filter = request.args.get('enterprise', None)
        
        cur = conn.cursor()
        
        # Get diagram
        cur.execute('''
            SELECT id, plantuml_code, title, enterprise_filter, encoded_url, elements_count, relationships_count, created_at, updated_at
            FROM plantumldiagrams
            WHERE id = ?
        ''', (diagram_id,))
        
        diagram_row = cur.fetchone()
        if not diagram_row:
            cur.close()
            conn.close()
            return jsonify({'error': 'Diagram not found'}), 404
        
        # Validate repository scoping if enterprise filter is provided
        if enterprise_filter:
            diagram_enterprise = diagram_row[3]  # enterprise_filter is at index 3
            if (diagram_enterprise or "").lower() != enterprise_filter.lower():
                cur.close()
                conn.close()
                return jsonify({
                    'error': f'Repository scoping violation: Diagram belongs to repository "{diagram_enterprise}", not "{enterprise_filter}"'
                }), 403
        
        columns = [desc[0] for desc in cur.description]
        diagram = dict(zip(columns, diagram_row))
        
        # Get associated elements
        cur.execute('''
            SELECT e.id, e.name, e.description, e.enterprise, e.facet, e.element, e.image_url
            FROM plantumldiagram_elements pde
            JOIN domainmodel e ON pde.element_id = e.id
            WHERE pde.diagram_id = ?
            ORDER BY e.name
        ''', (diagram_id,))
        
        element_columns = [desc[0] for desc in cur.description]
        elements = [dict(zip(element_columns, row)) for row in cur.fetchall()]
        diagram['elements'] = elements
        
        cur.close()
        conn.close()
        return jsonify(diagram)
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/diagrams/<int:diagram_id>', methods=['PUT', 'PATCH'])
def update_diagram(diagram_id):
    """Update a diagram. Supports updating:
    - title
    - plantuml_code
    - encoded_url (encoded PlantUML string)
    - elements_count
    - relationships_count
    - enterprise_filter
    - element_ids (updates the plantumldiagram_elements junction table)
    """
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        cur = conn.cursor()
        
        # Check if diagram exists and get current enterprise_filter for validation
        cur.execute('SELECT id, enterprise_filter FROM plantumldiagrams WHERE id = ?', (diagram_id,))
        diagram_check = cur.fetchone()
        if not diagram_check:
            cur.close()
            conn.close()
            return jsonify({'error': 'Diagram not found'}), 404
        
        current_enterprise_filter = diagram_check[1]  # enterprise_filter is at index 1
        # Use updated enterprise_filter if provided, otherwise use current
        updated_enterprise_filter = data.get('enterprise_filter', current_enterprise_filter)
        if updated_enterprise_filter is None:
            updated_enterprise_filter = current_enterprise_filter
        
        # Build update list for diagram table
        updates = []
        params = []
        
        if 'title' in data:
            updates.append('title = ?')
            params.append(data['title'])
        
        if 'plantuml_code' in data:
            updates.append('plantuml_code = ?')
            params.append(data['plantuml_code'])
        
        if 'encoded' in data or 'encoded_url' in data:
            # Handle encoded string (preferred field name is 'encoded')
            encoded = data.get('encoded') or data.get('encoded_url', '')
            # If it's a full URL, extract the encoded part
            if 'plantuml.com' in str(encoded):
                import re
                match = re.search(r'plantuml/[^/]+/~?1?([^/\?]+)', str(encoded))
                if match:
                    encoded = match.group(1)
                    if encoded.startswith('~1'):
                        encoded = encoded[2:]
            updates.append('encoded_url = ?')
            params.append(encoded)
        
        if 'elements_count' in data:
            updates.append('elements_count = ?')
            params.append(int(data['elements_count']))
        
        if 'relationships_count' in data:
            updates.append('relationships_count = ?')
            params.append(int(data['relationships_count']))
        
        if 'enterprise_filter' in data:
            updates.append('enterprise_filter = ?')
            params.append(data['enterprise_filter'] if data['enterprise_filter'] else None)
        
        # Update diagram table if there are any field updates
        if updates:
            updates.append('updated_at = CURRENT_TIMESTAMP')
            params.append(diagram_id)
            query = f'UPDATE plantumldiagrams SET {", ".join(updates)} WHERE id = ?'
            cur.execute(query, params)
            conn.commit()
            cur.execute('SELECT * FROM plantumldiagrams WHERE id = ?', (diagram_id,))
            columns = [desc[0] for desc in cur.description]
            diagram = dict(zip(columns, cur.fetchone()))
        else:
            # No diagram table updates, just fetch the current diagram
            cur.execute('SELECT * FROM plantumldiagrams WHERE id = ?', (diagram_id,))
            columns = [desc[0] for desc in cur.description]
            diagram = dict(zip(columns, cur.fetchone()))
        
        # Update element references if element_ids is provided
        if 'element_ids' in data:
            element_ids = data['element_ids']
            if not isinstance(element_ids, list):
                element_ids = []
            
            # Validate repository scoping: ensure all element_ids belong to the enterprise_filter
            if element_ids and updated_enterprise_filter:
                # Check if all elements belong to the specified enterprise
                placeholders = ','.join(['?'] * len(element_ids))
                cur.execute(f'''
                    SELECT id, enterprise, name
                    FROM domainmodel
                    WHERE id IN ({placeholders})
                ''', element_ids)
                
                elements_data = cur.fetchall()
                invalid_elements = []
                for elem in elements_data:
                    elem_id, elem_enterprise, elem_name = elem
                    if (elem_enterprise or "").lower() != updated_enterprise_filter.lower():
                        invalid_elements.append(f"{elem_name} (ID: {elem_id})")
                
                if invalid_elements:
                    cur.close()
                    conn.close()
                    return jsonify({
                        'error': f'Repository scoping violation: The following elements do not belong to repository "{updated_enterprise_filter}": {", ".join(invalid_elements)}'
                    }), 400
            
            # Delete existing element references
            cur.execute('DELETE FROM plantumldiagram_elements WHERE diagram_id = ?', (diagram_id,))
            
            # Insert new element references
            for element_id in element_ids:
                cur.execute('''
                    INSERT OR IGNORE INTO plantumldiagram_elements (diagram_id, element_id, created_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                ''', (diagram_id, element_id))
        
        conn.commit()
        
        # Get associated elements for response
        cur.execute('''
            SELECT e.id, e.name, e.description, e.enterprise, e.facet, e.element, e.image_url
            FROM plantumldiagram_elements pde
            JOIN domainmodel e ON pde.element_id = e.id
            WHERE pde.diagram_id = ?
            ORDER BY e.name
        ''', (diagram_id,))
        
        element_columns = [desc[0] for desc in cur.description]
        elements = [dict(zip(element_columns, row)) for row in cur.fetchall()]
        diagram['elements'] = elements
        
        cur.close()
        conn.close()
        return jsonify(diagram)
    except Exception as e:
        if conn:
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/diagrams/<int:diagram_id>', methods=['DELETE'])
def delete_diagram(diagram_id):
    """Delete a diagram (cascade will delete element references)"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM plantumldiagrams WHERE id = ?', (diagram_id,))
        conn.commit()
        # Check if row was deleted
        if cur.rowcount == 0:
            cur.close()
            conn.close()
            return jsonify({'error': 'Diagram not found'}), 404
        # Fetch the deleted diagram details before closing
        cur.execute('SELECT * FROM plantumldiagrams WHERE id = ?', (diagram_id,))
        deleted_diagram = cur.fetchone()
        if deleted_diagram:
            columns = [desc[0] for desc in cur.description]
            diagram = dict(zip(columns, deleted_diagram))
        else:
            diagram = {'id': diagram_id}
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'message': 'Diagram deleted successfully', 'diagram': diagram})
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

# ============================================================================
# Canvas Property Instances API Endpoints
# ============================================================================

@app.route('/api/canvas/properties/palette', methods=['GET'])
def get_properties_for_palette():
    """Get all unique properties for the palette"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT DISTINCT 
                dep.id,
                dep.propertyname,
                dep.ragtype,
                dep.description,
                dep.image_url
            FROM domainelementproperties dep
            WHERE dep.propertyname IS NOT NULL
            ORDER BY dep.propertyname, dep.ragtype
        ''')
        columns = [desc[0] for desc in cur.description]
        properties = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify(properties)
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/property-instances', methods=['POST'])
def create_property_instance():
    """Create a new property instance on canvas"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.json
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO canvas_property_instances
            (canvas_model_id, property_id, element_instance_id, instance_name, x_position, y_position, width, height, z_index, source, rule_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['canvas_model_id'],
            data['property_id'],
            data['element_instance_id'],
            data['instance_name'],
            data['x_position'],
            data['y_position'],
            data.get('width', 100),
            data.get('height', 30),
            data.get('z_index', 0),
            data.get('source'),
            data.get('rule_id')
        ))
        property_instance_id = cur.lastrowid
        
        # Get property template data
        cur.execute('''
            SELECT propertyname, ragtype, image_url, description
            FROM domainelementproperties
            WHERE id = ?
        ''', (data['property_id'],))
        prop_data = cur.fetchone()
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            'id': property_instance_id,
            'canvas_model_id': data['canvas_model_id'],
            'property_id': data['property_id'],
            'element_instance_id': data['element_instance_id'],
            'instance_name': data['instance_name'],
            'x_position': data['x_position'],
            'y_position': data['y_position'],
            'width': data.get('width', 100),
            'height': data.get('height', 30),
            'z_index': data.get('z_index', 0),
            'source': data.get('source'),
            'rule_id': data.get('rule_id'),
            'propertyname': prop_data[0] if prop_data else '',
            'ragtype': prop_data[1] if prop_data else None,
            'image_url': prop_data[2] if prop_data else None,
            'description': prop_data[3] if prop_data else None
        }), 201
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/property-instances/<int:property_instance_id>', methods=['PUT'])
def update_property_instance(property_instance_id):
    """Update a property instance"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.json
        updates = []
        params = []
        
        if 'instance_name' in data:
            updates.append('instance_name = ?')
            params.append(data['instance_name'])
        if 'x_position' in data:
            updates.append('x_position = ?')
            params.append(data['x_position'])
        if 'y_position' in data:
            updates.append('y_position = ?')
            params.append(data['y_position'])
        if 'width' in data:
            updates.append('width = ?')
            params.append(data['width'])
        if 'height' in data:
            updates.append('height = ?')
            params.append(data['height'])
        
        if not updates:
            return jsonify({'error': 'No fields to update'}), 400
        
        updates.append('updated_at = CURRENT_TIMESTAMP')
        params.append(property_instance_id)
        
        cur = conn.cursor()
        cur.execute(f'''
            UPDATE canvas_property_instances
            SET {', '.join(updates)}
            WHERE id = ?
        ''', params)
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({'message': 'Property instance updated successfully'}), 200
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/property-instances/<int:property_instance_id>', methods=['DELETE'])
def delete_property_instance(property_instance_id):
    """Delete a property instance"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM canvas_property_instances WHERE id = ?', (property_instance_id,))
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({'message': 'Property instance deleted successfully'}), 200
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/models/<int:model_id>/property-instances', methods=['GET'])
def get_property_instances_for_model(model_id):
    """Get all property instances for a canvas model"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT 
                cpi.id,
                cpi.canvas_model_id,
                cpi.property_id,
                cpi.element_instance_id,
                cpi.instance_name,
                cpi.x_position,
                cpi.y_position,
                cpi.width,
                cpi.height,
                cpi.z_index,
                cpi.source,
                cpi.rule_id,
                dep.propertyname,
                dep.ragtype,
                dep.image_url,
                dep.description
            FROM canvas_property_instances cpi
            JOIN domainelementproperties dep ON cpi.property_id = dep.id
            WHERE cpi.canvas_model_id = ?
            ORDER BY cpi.z_index, cpi.id
        ''', (model_id,))
        columns = [desc[0] for desc in cur.description]
        property_instances = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify(property_instances)
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/element-instances', methods=['POST'])
def create_element_instance():
    """Create a new element instance in the database"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Validate required fields
        if 'canvas_model_id' not in data or 'element_type_id' not in data or 'instance_name' not in data:
            return jsonify({'error': 'Missing required fields: canvas_model_id, element_type_id, instance_name'}), 400
        
        cur = conn.cursor()

        ok, error = enforce_element_occurrence_limit(conn, occurrences_to_add=1)
        if not ok:
            cur.close()
            conn.close()
            return jsonify(error), 403
        
        # Insert element instance
        cur.execute('''
            INSERT INTO canvas_element_instances
            (canvas_model_id, element_type_id, instance_name, description, x_position, y_position, width, height, z_index)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['canvas_model_id'],
            data['element_type_id'],
            data['instance_name'],
            data.get('description'),
            data.get('x_position', 0),
            data.get('y_position', 0),
            data.get('width', 120),
            data.get('height', 120),
            data.get('z_index', 0)
        ))
        
        instance_id = cur.lastrowid
        
        # Get the created instance with element type info
        cur.execute('''
            SELECT 
                cei.id,
                cei.canvas_model_id,
                cei.element_type_id,
                cei.instance_name,
                cei.x_position,
                cei.y_position,
                cei.width,
                cei.height,
                cei.z_index,
                dm.element as element_type,
                dm.image_url as element_image_url
            FROM canvas_element_instances cei
            JOIN domainmodel dm ON cei.element_type_id = dm.id
            WHERE cei.id = ?
        ''', (instance_id,))
        
        columns = [desc[0] for desc in cur.description]
        instance = dict(zip(columns, cur.fetchone()))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify(instance), 201
        
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ============================================================================
# Canvas API Endpoints
# ============================================================================

@app.route('/api/canvas/element-instances/by-type/<int:element_type_id>', methods=['GET'])
def get_element_instances_by_type(element_type_id):
    """Get all element instances of a specific element type from all models (repository-wide)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Get all element instances of this type across all models
        cur.execute('''
            SELECT 
                cei.id,
                cei.canvas_model_id,
                cei.element_type_id,
                cei.instance_name,
                cei.description,
                cei.x_position,
                cei.y_position,
                cei.width,
                cei.height,
                cei.z_index,
                cei.created_at,
                cei.updated_at,
                dm.element as element_type,
                dm.image_url as element_image_url,
                cm.name as model_name
            FROM canvas_element_instances cei
            JOIN domainmodel dm ON cei.element_type_id = dm.id
            LEFT JOIN canvas_models cm ON cei.canvas_model_id = cm.id
            WHERE cei.element_type_id = ?
            ORDER BY cei.created_at DESC, cei.instance_name
        ''', (element_type_id,))
        
        columns = [desc[0] for desc in cur.description]
        instances = []
        for row in cur.fetchall():
            instance = dict(zip(columns, row))
            # Get properties for this instance
            cur.execute('''
                SELECT 
                    cpi.id,
                    cpi.property_id,
                    cpi.instance_name,
                    cpi.source,
                    cpi.rule_id,
                    dep.propertyname,
                    dep.ragtype,
                    dep.image_url,
                    dep.description
                FROM canvas_property_instances cpi
                JOIN domainelementproperties dep ON cpi.property_id = dep.id
                WHERE cpi.element_instance_id = ?
            ''', (instance['id'],))
            
            prop_columns = [desc[0] for desc in cur.description]
            properties = []
            for prop_row in cur.fetchall():
                prop = dict(zip(prop_columns, prop_row))
                properties.append({
                    'id': prop['id'],
                    'property_id': prop['property_id'],
                    'instance_name': prop['instance_name'],
                    'source': prop['source'],
                    'rule_id': prop['rule_id'],
                    'propertyname': prop['propertyname'],
                    'ragtype': prop['ragtype'],
                    'image_url': prop['image_url'],
                    'description': prop['description']
                })
            
            instance['properties'] = properties
            
            # Get relationships for this instance (as source)
            cur.execute('''
                SELECT 
                    cr.id,
                    cr.target_instance_id,
                    cr.relationship_type,
                    cei.instance_name as target_instance_name,
                    cei.element_type_id as target_element_type_id,
                    dm.element as target_element_type
                FROM canvas_relationships cr
                JOIN canvas_element_instances cei ON cr.target_instance_id = cei.id
                JOIN domainmodel dm ON cei.element_type_id = dm.id
                WHERE cr.source_instance_id = ?
            ''', (instance['id'],))
            
            rel_columns = [desc[0] for desc in cur.description]
            relationships = []
            for rel_row in cur.fetchall():
                rel = dict(zip(rel_columns, rel_row))
                relationships.append({
                    'id': rel['id'],
                    'target_instance_id': rel['target_instance_id'],
                    'target_instance_name': rel['target_instance_name'],
                    'target_element_type_id': rel['target_element_type_id'],
                    'target_element_type': rel['target_element_type'],
                    'relationship_type': rel['relationship_type']
                })
            
            # Get relationships for this instance (as target)
            cur.execute('''
                SELECT 
                    cr.id,
                    cr.source_instance_id,
                    cr.relationship_type,
                    cei.instance_name as source_instance_name,
                    cei.element_type_id as source_element_type_id,
                    dm.element as source_element_type
                FROM canvas_relationships cr
                JOIN canvas_element_instances cei ON cr.source_instance_id = cei.id
                JOIN domainmodel dm ON cei.element_type_id = dm.id
                WHERE cr.target_instance_id = ?
            ''', (instance['id'],))
            
            rel_columns = [desc[0] for desc in cur.description]
            incoming_relationships = []
            for rel_row in cur.fetchall():
                rel = dict(zip(rel_columns, rel_row))
                incoming_relationships.append({
                    'id': rel['id'],
                    'source_instance_id': rel['source_instance_id'],
                    'source_instance_name': rel['source_instance_name'],
                    'source_element_type_id': rel['source_element_type_id'],
                    'source_element_type': rel['source_element_type'],
                    'relationship_type': rel['relationship_type']
                })
            
            instance['relationships'] = relationships
            instance['incoming_relationships'] = incoming_relationships
            instance['image_url'] = instance['element_image_url']  # Use element type image
            instances.append(instance)
        
        cur.close()
        conn.close()
        return jsonify(instances)
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/element-instances/<int:instance_id>', methods=['PUT'])
def update_element_instance(instance_id):
    """Update an element instance"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        updates = []
        params = []
        
        if 'instance_name' in data:
            updates.append('instance_name = ?')
            params.append(data['instance_name'])
        if 'description' in data:
            updates.append('description = ?')
            params.append(data['description'])
        if 'x_position' in data:
            updates.append('x_position = ?')
            params.append(data['x_position'])
        if 'y_position' in data:
            updates.append('y_position = ?')
            params.append(data['y_position'])
        if 'width' in data:
            updates.append('width = ?')
            params.append(data['width'])
        if 'height' in data:
            updates.append('height = ?')
            params.append(data['height'])
        
        if not updates:
            return jsonify({'error': 'No fields to update'}), 400
        
        updates.append('updated_at = CURRENT_TIMESTAMP')
        params.append(instance_id)
        
        cur = conn.cursor()
        cur.execute(f'''
            UPDATE canvas_element_instances
            SET {', '.join(updates)}
            WHERE id = ?
        ''', params)
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({'message': 'Element instance updated successfully'}), 200
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/models', methods=['POST'])
def create_canvas_model():
    """Create a new canvas model"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        cur = conn.cursor()

        ok, error = enforce_model_limit(conn)
        if not ok:
            cur.close()
            conn.close()
            return jsonify(error), 403

        element_instances = data.get('elements', [])
        ok, error = enforce_element_occurrence_limit(conn, occurrences_to_add=len(element_instances))
        if not ok:
            cur.close()
            conn.close()
            return jsonify(error), 403
        
        # Insert canvas model
        cur.execute('''
            INSERT INTO canvas_models 
            (name, description, canvas_width, canvas_height, zoom_level, pan_x, pan_y, canvas_template, template_zoom, template_pan_x, template_pan_y)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('name', 'Untitled Model'),
            data.get('description'),
            data.get('canvas_width', 2000),
            data.get('canvas_height', 2000),
            data.get('zoom_level', 1.0),
            data.get('pan_x', 0),
            data.get('pan_y', 0),
            data.get('canvas_template', 'none'),
            data.get('template_zoom', 1.0),
            data.get('template_pan_x', 0),
            data.get('template_pan_y', 0)
        ))
        
        canvas_model_id = cur.lastrowid
        
        # Insert element instances
        instance_id_map = {}  # Map temporary IDs to database IDs
        
        for elem in element_instances:
            cur.execute('''
                INSERT INTO canvas_element_instances
                (canvas_model_id, element_type_id, instance_name, description, x_position, y_position, width, height, z_index)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                canvas_model_id,
                elem['element_type_id'],
                elem['instance_name'],
                elem.get('description'),
                elem['x_position'],
                elem['y_position'],
                elem.get('width', 120),
                elem.get('height', 120),
                elem.get('z_index', 0)
            ))
            instance_id = cur.lastrowid
            # Map temporary ID if provided, otherwise use database ID
            temp_id = elem.get('temp_id', instance_id)
            instance_id_map[temp_id] = instance_id
        
        # Insert relationships
        relationships = data.get('relationships', [])
        for rel in relationships:
            source_id = instance_id_map.get(rel['source_instance_id'], rel['source_instance_id'])
            target_id = instance_id_map.get(rel['target_instance_id'], rel['target_instance_id'])
            
            cur.execute('''
                INSERT INTO canvas_relationships
                (canvas_model_id, source_instance_id, target_instance_id, relationship_type, line_path)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                canvas_model_id,
                source_id,
                target_id,
                rel.get('relationship_type'),
                rel.get('line_path')
            ))
        
        # Insert property instances
        property_instances = data.get('property_instances', [])
        for prop in property_instances:
            # Skip rule-generated properties; they are re-evaluated after save
            if prop.get('source') == 'rules_engine' or prop.get('rule_id') is not None:
                continue
            # Map element_instance_id from temporary ID to database ID
            element_instance_id = instance_id_map.get(prop['element_instance_id'], prop['element_instance_id'])
            property_id = prop.get('property_id')
            
            # Validate property_id exists
            if not property_id:
                print(f"Warning: Property instance missing property_id, skipping: {prop}")
                continue
            
            # Check if property_id exists in domainelementproperties
            cur.execute('SELECT id FROM domainelementproperties WHERE id = ?', (property_id,))
            if not cur.fetchone():
                print(f"Warning: Property ID {property_id} does not exist in domainelementproperties, skipping property instance")
                continue
            
            # Check if element_instance_id exists in canvas_element_instances
            cur.execute('SELECT id FROM canvas_element_instances WHERE id = ?', (element_instance_id,))
            if not cur.fetchone():
                print(f"Warning: Element instance ID {element_instance_id} does not exist, skipping property instance")
                continue
            
            try:
                cur.execute('''
                    INSERT INTO canvas_property_instances
                    (canvas_model_id, property_id, element_instance_id, instance_name, x_position, y_position, width, height, z_index, source, rule_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    canvas_model_id,
                    property_id,
                    element_instance_id,
                    prop.get('instance_name', ''),
                    prop.get('x_position', 0),
                    prop.get('y_position', 0),
                    prop.get('width', 100),
                    prop.get('height', 30),
                    prop.get('z_index', 0),
                    prop.get('source'),
                    prop.get('rule_id')
                ))
            except sqlite3.IntegrityError as e:
                print(f"Error inserting property instance: {e}")
                print(f"Property instance data: {prop}")
                # Continue with other property instances instead of failing completely
                continue
        
        # Save template segments if provided
        if 'template_segments' in data and data['template_segments']:
            segments = data['template_segments']
            for segment in segments:
                cur.execute('''
                    INSERT INTO canvas_template_segments (canvas_model_id, segment_index, segment_name)
                    VALUES (?, ?, ?)
                ''', (canvas_model_id, segment.get('segment_index'), segment.get('segment_name')))
        
        conn.commit()
        
        # Evaluate all active design rules after model is created
        try:
            cur.execute('SELECT id FROM design_rules WHERE active = 1')
            active_rules = cur.fetchall()
            for rule_row in active_rules:
                rule_id = rule_row[0]
                evaluate_design_rule(cur, rule_id)
            conn.commit()
        except Exception as eval_error:
            # Don't fail model creation if rule evaluation fails
            print(f"[Design Rules] Error evaluating rules after model creation: {eval_error}")
            conn.rollback()
            # Re-commit the model creation
            conn.commit()
        
        cur.close()
        conn.close()
        
        return jsonify({
            'id': canvas_model_id,
            'name': data.get('name', 'Untitled Model'),
            'message': 'Canvas model saved successfully'
        }), 201
        
    except sqlite3.IntegrityError as e:
        if conn:
            conn.rollback()
            conn.close()
        error_msg = str(e)
        if 'FOREIGN KEY constraint failed' in error_msg:
            return jsonify({
                'error': 'Foreign key constraint failed. Some property instances reference invalid properties or element instances. Please check that all properties and elements exist.',
                'details': error_msg
            }), 400
        return jsonify({'error': f'Database integrity error: {error_msg}'}), 400
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/models', methods=['GET'])
def get_canvas_models():
    """Get all canvas models"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT id, name, description, canvas_width, canvas_height, 
                   zoom_level, pan_x, pan_y, created_at, updated_at
            FROM canvas_models
            ORDER BY updated_at DESC
        ''')
        
        models = []
        for row in cur.fetchall():
            models.append({
                'id': row[0],
                'name': row[1],
                'description': row[2],
                'canvas_width': row[3],
                'canvas_height': row[4],
                'zoom_level': row[5],
                'pan_x': row[6],
                'pan_y': row[7],
                'created_at': row[8],
                'updated_at': row[9]
            })
        
        cur.close()
        conn.close()
        return jsonify(models)
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/models/<int:model_id>', methods=['GET'])
def get_canvas_model(model_id):
    """Get a specific canvas model with all elements and relationships"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Get canvas model (with template fields if they exist)
        try:
            cur.execute('''
                SELECT id, name, description, canvas_width, canvas_height, 
                       zoom_level, pan_x, pan_y, canvas_template, template_zoom, 
                       template_pan_x, template_pan_y, created_at, updated_at
                FROM canvas_models
                WHERE id = ?
            ''', (model_id,))
        except sqlite3.OperationalError:
            # Fallback if template columns don't exist
            cur.execute('''
                SELECT id, name, description, canvas_width, canvas_height, 
                       zoom_level, pan_x, pan_y, created_at, updated_at
                FROM canvas_models
                WHERE id = ?
            ''', (model_id,))
        
        model_row = cur.fetchone()
        if not model_row:
            cur.close()
            conn.close()
            return jsonify({'error': 'Canvas model not found'}), 404
        
        # Handle both old and new schema (with/without template fields)
        if len(model_row) >= 14:
            # New schema with template fields
            model = {
                'id': model_row[0],
                'name': model_row[1],
                'description': model_row[2],
                'canvas_width': model_row[3],
                'canvas_height': model_row[4],
                'zoom_level': model_row[5],
                'pan_x': model_row[6],
                'pan_y': model_row[7],
                'canvas_template': model_row[8] if model_row[8] else 'none',
                'template_zoom': model_row[9] if model_row[9] else 1.0,
                'template_pan_x': model_row[10] if model_row[10] else 0,
                'template_pan_y': model_row[11] if model_row[11] else 0,
                'created_at': model_row[12],
                'updated_at': model_row[13],
                'elements': [],
                'relationships': [],
                'property_instances': [],
                'template_segments': []
            }
        else:
            # Old schema without template fields
            model = {
                'id': model_row[0],
                'name': model_row[1],
                'description': model_row[2],
                'canvas_width': model_row[3],
                'canvas_height': model_row[4],
                'zoom_level': model_row[5],
                'pan_x': model_row[6],
                'pan_y': model_row[7],
                'canvas_template': 'none',
                'template_zoom': 1.0,
                'template_pan_x': 0,
                'template_pan_y': 0,
                'created_at': model_row[8],
                'updated_at': model_row[9],
                'elements': [],
                'relationships': [],
                'property_instances': [],
                'template_segments': []
            }
        
        # Get template segments
        cur.execute('''
            SELECT segment_index, segment_name
            FROM canvas_template_segments
            WHERE canvas_model_id = ?
            ORDER BY segment_index
        ''', (model_id,))
        
        for row in cur.fetchall():
            model['template_segments'].append({
                'segment_index': row[0],
                'segment_name': row[1]
            })
        
        # Get element instances with element type info
        cur.execute('''
            SELECT 
                cei.id,
                cei.element_type_id,
                cei.instance_name,
                cei.description,
                cei.x_position,
                cei.y_position,
                cei.width,
                cei.height,
                cei.z_index,
                cei.created_at,
                cei.updated_at,
                dm.name as element_type_name,
                dm.element as element_type,
                dm.facet,
                dm.enterprise,
                dm.image_url as element_image_url
            FROM canvas_element_instances cei
            JOIN domainmodel dm ON cei.element_type_id = dm.id
            WHERE cei.canvas_model_id = ?
            ORDER BY cei.z_index, cei.id
        ''', (model_id,))
        
        for row in cur.fetchall():
            model['elements'].append({
                'id': row[0],
                'element_type_id': row[1],
                'instance_name': row[2],
                'description': row[3],
                'x_position': row[4],
                'y_position': row[5],
                'width': row[6],
                'height': row[7],
                'z_index': row[8],
                'created_at': row[9],
                'updated_at': row[10],
                'element_type_name': row[11],
                'element_type': row[12],
                'facet': row[13],
                'enterprise': row[14],
                'element_image_url': row[15]
            })
        
        # Get relationships
        cur.execute('''
            SELECT 
                cr.id,
                cr.source_instance_id,
                cr.target_instance_id,
                cr.relationship_type,
                cr.line_path,
                cei1.instance_name as source_name,
                cei2.instance_name as target_name
            FROM canvas_relationships cr
            JOIN canvas_element_instances cei1 ON cr.source_instance_id = cei1.id
            JOIN canvas_element_instances cei2 ON cr.target_instance_id = cei2.id
            WHERE cr.canvas_model_id = ?
        ''', (model_id,))
        
        for row in cur.fetchall():
            model['relationships'].append({
                'id': row[0],
                'source_instance_id': row[1],
                'target_instance_id': row[2],
                'relationship_type': row[3],
                'line_path': row[4],
                'source_name': row[5],
                'target_name': row[6]
            })
        
        # Get property instances (explicit for this model)
        cur.execute('''
            SELECT 
                cpi.id,
                cpi.property_id,
                cpi.element_instance_id,
                cpi.instance_name,
                cpi.x_position,
                cpi.y_position,
                cpi.width,
                cpi.height,
                cpi.z_index,
                cpi.source,
                cpi.rule_id,
                dep.propertyname,
                dep.ragtype,
                dep.image_url
            FROM canvas_property_instances cpi
            JOIN domainelementproperties dep ON cpi.property_id = dep.id
            WHERE cpi.canvas_model_id = ?
            ORDER BY cpi.z_index, cpi.id
        ''', (model_id,))
        
        explicit_property_instances = []
        explicit_property_map = {}
        for row in cur.fetchall():
            prop = {
                'id': row[0],
                'property_id': row[1],
                'element_instance_id': row[2],
                'instance_name': row[3],
                'x_position': row[4],
                'y_position': row[5],
                'width': row[6],
                'height': row[7],
                'z_index': row[8],
                'source': row[9],
                'rule_id': row[10],
                'propertyname': row[11],
                'ragtype': row[12],
                'image_url': row[13]
            }
            explicit_property_instances.append(prop)
            explicit_property_map.setdefault(row[2], []).append(prop)

        # Inherit properties from canonical occurrences (same name/type) without creating new DB rows
        element_lookup = {elem['id']: elem for elem in model['elements']}
        missing_property_ids = [elem['id'] for elem in model['elements'] if elem['id'] not in explicit_property_map]
        inherited_properties = []
        if missing_property_ids:
            for elem_id in missing_property_ids:
                elem = element_lookup.get(elem_id)
                if not elem:
                    continue
                cur.execute('''
                    SELECT MIN(cei2.id)
                    FROM canvas_element_instances cei2
                    JOIN canvas_models cm2 ON cei2.canvas_model_id = cm2.id
                    WHERE (cm2.name IS NULL OR cm2.name NOT LIKE 'Impact:%')
                      AND cei2.element_type_id = ?
                      AND LOWER(COALESCE(cei2.instance_name, '')) = LOWER(COALESCE(?, ''))
                ''', (elem['element_type_id'], elem.get('instance_name')))
                row = cur.fetchone()
                canonical_id = row[0] if row else None
                if not canonical_id or canonical_id == elem_id:
                    continue
                cur.execute('''
                    SELECT 
                        cpi.property_id,
                        cpi.instance_name,
                        dep.propertyname,
                        dep.ragtype,
                        dep.image_url
                    FROM canvas_property_instances cpi
                    JOIN domainelementproperties dep ON cpi.property_id = dep.id
                    WHERE cpi.element_instance_id = ?
                    ORDER BY cpi.id
                ''', (canonical_id,))
                props = cur.fetchall()
                if not props:
                    continue
                prop_width = 120
                prop_height = 40
                base_x = elem.get('x_position', 0)
                base_y = (elem.get('y_position', 0) or 0) + (elem.get('height') or 120) + 20
                for idx, prop in enumerate(props):
                    inherited_properties.append({
                        'id': None,
                        'property_id': prop[0],
                        'element_instance_id': elem_id,
                        'instance_name': prop[1],
                        'x_position': base_x,
                        'y_position': base_y + (idx * prop_height),
                        'width': prop_width,
                        'height': prop_height,
                        'z_index': 0,
                        'source': 'inherited',
                        'rule_id': None,
                        'propertyname': prop[2],
                        'ragtype': prop[3],
                        'image_url': prop[4]
                    })

        model['property_instances'].extend(explicit_property_instances + inherited_properties)
        
        cur.close()
        conn.close()
        return jsonify(model)
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/models/<int:model_id>', methods=['PUT'])
def update_canvas_model(model_id):
    """Update a canvas model"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        cur = conn.cursor()
        
        # Check if model exists
        cur.execute('SELECT id FROM canvas_models WHERE id = ?', (model_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'error': 'Canvas model not found'}), 404
        
        # Update canvas model
        updates = []
        params = []
        
        if 'name' in data:
            updates.append('name = ?')
            params.append(data['name'])
        if 'description' in data:
            updates.append('description = ?')
            params.append(data['description'])
        if 'canvas_width' in data:
            updates.append('canvas_width = ?')
            params.append(data['canvas_width'])
        if 'canvas_height' in data:
            updates.append('canvas_height = ?')
            params.append(data['canvas_height'])
        if 'zoom_level' in data:
            updates.append('zoom_level = ?')
            params.append(data['zoom_level'])
        if 'pan_x' in data:
            updates.append('pan_x = ?')
            params.append(data['pan_x'])
        if 'pan_y' in data:
            updates.append('pan_y = ?')
            params.append(data['pan_y'])
        if 'canvas_template' in data:
            updates.append('canvas_template = ?')
            params.append(data['canvas_template'])
        if 'template_zoom' in data:
            updates.append('template_zoom = ?')
            params.append(data['template_zoom'])
        if 'template_pan_x' in data:
            updates.append('template_pan_x = ?')
            params.append(data['template_pan_x'])
        if 'template_pan_y' in data:
            updates.append('template_pan_y = ?')
            params.append(data['template_pan_y'])
        
        if updates:
            updates.append('updated_at = CURRENT_TIMESTAMP')
            params.append(model_id)
            cur.execute(f'UPDATE canvas_models SET {", ".join(updates)} WHERE id = ?', params)
        
        # Update or replace elements if provided
        if 'elements' in data:
            cur.execute('SELECT COUNT(*) FROM canvas_element_instances')
            total_occurrences = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM canvas_element_instances WHERE canvas_model_id = ?', (model_id,))
            current_model_occurrences = cur.fetchone()[0]
            projected_total = total_occurrences - current_model_occurrences + len(data['elements'])
            if CE_LIMITS_ENABLED and CE_MAX_ELEMENT_OCCURRENCES > 0 and projected_total > CE_MAX_ELEMENT_OCCURRENCES:
                cur.close()
                conn.close()
                return jsonify({
                    'error': 'Element occurrence limit reached',
                    'limit': CE_MAX_ELEMENT_OCCURRENCES,
                    'current': total_occurrences
                }), 403

            # Delete existing elements
            cur.execute('DELETE FROM canvas_element_instances WHERE canvas_model_id = ?', (model_id,))
            # Delete existing relationships (they depend on elements)
            cur.execute('DELETE FROM canvas_relationships WHERE canvas_model_id = ?', (model_id,))
            # Delete existing property instances (they depend on elements)
            cur.execute('DELETE FROM canvas_property_instances WHERE canvas_model_id = ?', (model_id,))
            
            # Insert new elements
            instance_id_map = {}
            for elem in data['elements']:
                cur.execute('''
                    INSERT INTO canvas_element_instances
                    (canvas_model_id, element_type_id, instance_name, description, x_position, y_position, width, height, z_index)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    model_id,
                    elem['element_type_id'],
                    elem['instance_name'],
                    elem.get('description'),
                    elem['x_position'],
                    elem['y_position'],
                    elem.get('width', 120),
                    elem.get('height', 120),
                    elem.get('z_index', 0)
                ))
                instance_id = cur.lastrowid
                temp_id = elem.get('temp_id', instance_id)
                instance_id_map[temp_id] = instance_id
            
            # Insert new relationships
            if 'relationships' in data:
                for rel in data['relationships']:
                    source_id = instance_id_map.get(rel['source_instance_id'], rel['source_instance_id'])
                    target_id = instance_id_map.get(rel['target_instance_id'], rel['target_instance_id'])
                    
                    cur.execute('''
                        INSERT INTO canvas_relationships
                        (canvas_model_id, source_instance_id, target_instance_id, relationship_type, line_path)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (
                        model_id,
                        source_id,
                        target_id,
                        rel.get('relationship_type'),
                        rel.get('line_path')
                    ))
            
            # Insert new property instances
            if 'property_instances' in data:
                for prop in data['property_instances']:
                    # Skip rule-generated properties; they are re-evaluated after save
                    if prop.get('source') == 'rules_engine' or prop.get('rule_id') is not None:
                        continue
                    # Map element_instance_id from temporary ID to database ID
                    element_instance_id = instance_id_map.get(prop['element_instance_id'], prop['element_instance_id'])
                    property_id = prop.get('property_id')
                    
                    # Validate property_id exists
                    if not property_id:
                        print(f"Warning: Property instance missing property_id, skipping: {prop}")
                        continue
                    
                    # Check if property_id exists in domainelementproperties
                    cur.execute('SELECT id FROM domainelementproperties WHERE id = ?', (property_id,))
                    if not cur.fetchone():
                        print(f"Warning: Property ID {property_id} does not exist in domainelementproperties, skipping property instance")
                        continue
                    
                    # Check if element_instance_id exists in canvas_element_instances
                    cur.execute('SELECT id FROM canvas_element_instances WHERE id = ?', (element_instance_id,))
                    if not cur.fetchone():
                        print(f"Warning: Element instance ID {element_instance_id} does not exist, skipping property instance")
                        continue
                    
                    try:
                        cur.execute('''
                            INSERT INTO canvas_property_instances
                            (canvas_model_id, property_id, element_instance_id, instance_name, x_position, y_position, width, height, z_index, source, rule_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            model_id,
                            property_id,
                            element_instance_id,
                            prop.get('instance_name', ''),
                            prop.get('x_position', 0),
                            prop.get('y_position', 0),
                            prop.get('width', 100),
                            prop.get('height', 30),
                            prop.get('z_index', 0),
                            prop.get('source'),
                            prop.get('rule_id')
                        ))
                    except sqlite3.IntegrityError as e:
                        print(f"Error inserting property instance: {e}")
                        print(f"Property instance data: {prop}")
                        # Continue with other property instances instead of failing completely
                        continue
            
            # Save template segments if provided
            if 'template_segments' in data and data['template_segments']:
                # Delete existing segments
                cur.execute('DELETE FROM canvas_template_segments WHERE canvas_model_id = ?', (model_id,))
                
                # Insert new segments
                segments = data['template_segments']
                for segment in segments:
                    cur.execute('''
                        INSERT INTO canvas_template_segments (canvas_model_id, segment_index, segment_name)
                        VALUES (?, ?, ?)
                    ''', (model_id, segment.get('segment_index'), segment.get('segment_name')))
        
        conn.commit()
        
        # Evaluate all active design rules after model is updated (if elements were updated)
        if 'elements' in data:
            try:
                cur.execute('SELECT id FROM design_rules WHERE active = 1')
                active_rules = cur.fetchall()
                for rule_row in active_rules:
                    rule_id = rule_row[0]
                    evaluate_design_rule(cur, rule_id)
                conn.commit()
            except Exception as eval_error:
                # Don't fail model update if rule evaluation fails
                print(f"[Design Rules] Error evaluating rules after model update: {eval_error}")
                conn.rollback()
                # Re-commit the model update
                conn.commit()
        
        cur.close()
        conn.close()
        
        return jsonify({'message': 'Canvas model updated successfully'}), 200
        
    except sqlite3.IntegrityError as e:
        if conn:
            conn.rollback()
            conn.close()
        error_msg = str(e)
        if 'FOREIGN KEY constraint failed' in error_msg:
            return jsonify({
                'error': 'Foreign key constraint failed. Some property instances reference invalid properties or element instances. Please check that all properties and elements exist.',
                'details': error_msg
            }), 400
        return jsonify({'error': f'Database integrity error: {error_msg}'}), 400
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/models/<int:model_id>', methods=['DELETE'])
def delete_canvas_model(model_id):
    """Delete a canvas model"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Check if model exists
        cur.execute('SELECT id FROM canvas_models WHERE id = ?', (model_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'error': 'Canvas model not found'}), 404
        
        # Delete model (CASCADE will delete elements and relationships)
        cur.execute('DELETE FROM canvas_models WHERE id = ?', (model_id,))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({'message': 'Canvas model deleted successfully'}), 200
        
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/models/<int:model_id>/template-segments', methods=['GET'])
def get_template_segments(model_id):
    """Get template segments for a canvas model"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT segment_index, segment_name
            FROM canvas_template_segments
            WHERE canvas_model_id = ?
            ORDER BY segment_index
        ''', (model_id,))
        
        segments = []
        for row in cur.fetchall():
            segments.append({
                'segment_index': row[0],
                'segment_name': row[1]
            })
        
        cur.close()
        conn.close()
        return jsonify(segments)
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/models/<int:model_id>/template-segments', methods=['POST'])
def save_template_segments(model_id):
    """Save template segments configuration for a canvas model"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.get_json()
        if not data or 'segments' not in data:
            return jsonify({'error': 'No segments data provided'}), 400
        
        cur = conn.cursor()
        
        # Check if model exists
        cur.execute('SELECT id FROM canvas_models WHERE id = ?', (model_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'error': 'Canvas model not found'}), 404
        
        # Delete existing segments
        cur.execute('DELETE FROM canvas_template_segments WHERE canvas_model_id = ?', (model_id,))
        
        # Insert new segments
        segments = data['segments']
        for segment in segments:
            cur.execute('''
                INSERT INTO canvas_template_segments (canvas_model_id, segment_index, segment_name)
                VALUES (?, ?, ?)
            ''', (model_id, segment['segment_index'], segment['segment_name']))
        
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'message': 'Template segments saved successfully'}), 200
        
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/models/<int:model_id>/element-segment-associations', methods=['GET'])
def get_element_segment_associations(model_id):
    """Get element-segment associations for a canvas model"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT element_instance_id, segment_index
            FROM canvas_element_segment_associations
            WHERE canvas_model_id = ?
        ''', (model_id,))
        
        associations = {}
        for row in cur.fetchall():
            associations[row[0]] = row[1]
        
        cur.close()
        conn.close()
        return jsonify(associations)
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/models/<int:model_id>/element-segment-associations', methods=['POST'])
def save_element_segment_association(model_id):
    """Associate an element instance with a segment"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        data = request.get_json()
        if 'element_instance_id' not in data or 'segment_index' not in data:
            return jsonify({'error': 'element_instance_id and segment_index required'}), 400
        
        cur = conn.cursor()
        
        # Check if model exists
        cur.execute('SELECT id FROM canvas_models WHERE id = ?', (model_id,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'error': 'Canvas model not found'}), 404
        
        element_instance_id = data['element_instance_id']
        segment_index = data['segment_index']
        
        # Delete existing association if any
        cur.execute('''
            DELETE FROM canvas_element_segment_associations
            WHERE canvas_model_id = ? AND element_instance_id = ?
        ''', (model_id, element_instance_id))
        
        # Insert new association
        cur.execute('''
            INSERT INTO canvas_element_segment_associations 
            (canvas_model_id, element_instance_id, segment_index)
            VALUES (?, ?, ?)
        ''', (model_id, element_instance_id, segment_index))
        
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'message': 'Element-segment association saved successfully'}), 200
        
    except Exception as e:
        if conn:
            conn.rollback()
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/relationship-rules', methods=['GET'])
def get_relationship_rules():
    """Get relationship rules from domainmodelrelationship for auto-connection"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        cur.execute('''
            SELECT DISTINCT
                dm1.element as source_element_type,
                dm2.element as target_element_type,
                dmr.relationship_type
            FROM domainmodelrelationship dmr
            JOIN domainmodel dm1 ON dmr.source_element_id = dm1.id
            JOIN domainmodel dm2 ON dmr.target_element_id = dm2.id
            WHERE dm1.element IS NOT NULL AND dm2.element IS NOT NULL
            ORDER BY dmr.relationship_type
        ''')
        
        rules = []
        for row in cur.fetchall():
            rules.append({
                'source_element_type': row[0],
                'target_element_type': row[1],
                'relationship_type': row[2]
            })
        
        cur.close()
        conn.close()
        return jsonify(rules)
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/canvas/init-process-flow', methods=['POST'])
def init_process_flow_endpoint():
    """Manually initialize Process -> Process flow relationship rule"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    
    try:
        cur = conn.cursor()
        
        # Check if Process -> Process flow relationship already exists
        cur.execute('''
            SELECT COUNT(*) FROM domainmodelrelationship dmr
            JOIN domainmodel dm1 ON dmr.source_element_id = dm1.id
            JOIN domainmodel dm2 ON dmr.target_element_id = dm2.id
            WHERE dm1.element = 'Process' 
            AND dm2.element = 'Process' 
            AND dmr.relationship_type = 'flow'
        ''')
        count = cur.fetchone()[0]
        
        if count > 0:
            conn.close()
            return jsonify({'message': 'Process flow relationship rule already exists', 'count': count}), 200
        
        # Find Process elements
        cur.execute('SELECT id FROM domainmodel WHERE element = ? ORDER BY id LIMIT 1', ('Process',))
        process_element = cur.fetchone()
        
        if not process_element:
            conn.close()
            return jsonify({'error': 'No Process elements found in database'}), 400
        
        # Use the same Process element for both source and target (self-referential)
        # This creates a valid relationship rule: Process -> Process flow
        source_id = process_element[0]
        target_id = process_element[0]
        
        # Check if this specific relationship already exists
        cur.execute('''
            SELECT id FROM domainmodelrelationship 
            WHERE source_element_id = ? AND target_element_id = ? AND relationship_type = ?
        ''', (source_id, target_id, 'flow'))
        
        if cur.fetchone():
            conn.close()
            return jsonify({'message': 'Process flow relationship rule already exists'}), 200
        
        # Create Process -> Process flow relationship (self-referential is allowed for rules)
        cur.execute('''
            INSERT INTO domainmodelrelationship 
            (source_element_id, target_element_id, relationship_type, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ''', (source_id, target_id, 'flow', 'Process flows to Process'))
        
        conn.commit()
        relationship_id = cur.lastrowid
        
        cur.close()
        conn.close()
        return jsonify({
            'message': 'Process flow relationship rule initialized successfully',
            'relationship_id': relationship_id,
            'source_element_id': source_id,
            'target_element_id': target_id
        }), 200
        
    except Exception as e:
        if conn:
            conn.close()
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("Starting DomainModel UI Server...")
    logging.info("Starting DomainModel UI Server...")
    try:
        # Initialize SQLite database on startup
        print("[Server] Initializing SQLite database...")
        logging.info("Initializing SQLite database...")
        if init_database():
            print("[Server] Database initialized successfully")
            logging.info("Database initialized successfully")
        else:
            print("[Server] Warning: Database initialization failed")
            logging.warning("Database initialization failed")
        print("Open your browser and navigate to: http://localhost:5000")
        logging.info("Starting Flask server on 127.0.0.1:5000")
        app.run(debug=False, use_reloader=False, host='127.0.0.1', port=5000)
    except Exception:
        logging.exception("Server failed to start")
        raise
