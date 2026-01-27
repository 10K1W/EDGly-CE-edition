# SaaS Migration Plan: EDGY Repository Modeller (Community Edition First)

## Executive Summary

This document outlines a two-step plan to move the EDGY Repository Modeller from a standalone desktop application to a hosted Community Edition (CE) for select and trial users, and then to a full multi-tenant SaaS. The CE phase keeps SQLite, adds custom authentication, and enforces usage limits. The SaaS phase introduces true organization-level tenancy and scalable infrastructure.

## Current Architecture

- **Backend**: Flask (Python) with SQLite database
- **Frontend**: Single-page HTML/JavaScript application
- **Database**: SQLite (single file, local storage)
- **Deployment**: Standalone Windows executable
- **Authentication**: None (single user)
- **Data Isolation**: None (all data in one database)

## Target Architecture

### Community Edition (Hosted Trial)
- **Backend**: Flask (current stack)
- **Frontend**: Existing HTML/JS SPA
- **Database**: SQLite (single file, per CE instance)
- **Deployment**: Free hosting with lightweight container (Render Free / Railway Free / Fly.io hobby)
- **Authentication**: Custom auth (email + password) with token-based sessions
- **Data Isolation**: User-based isolation within the single CE database
- **Limits**: Hard caps on element occurrences and models per user

### Full SaaS (Scalable)
- **Backend**: Flask/FastAPI
- **Frontend**: React/Vue.js SPA or enhanced HTML/JS
- **Database**: PostgreSQL (multi-tenant with row-level security)
- **Deployment**: Cloud-hosted (AWS, Azure, GCP, Render, Railway, or Heroku)
- **Authentication**: JWT-based with OAuth2 support
- **Data Isolation**: Organization-tenant isolation with per-tenant policies

---

## Phase 1: Community Edition Hosting (SQLite + Custom Auth)

### 1.1 Database Schema Changes (SQLite)

#### Add User Management Tables

```sql
-- Users table
CREATE TABLE users (
    id TEXT PRIMARY KEY, -- UUID stored as text for SQLite
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    company_name VARCHAR(255),
    subscription_tier VARCHAR(50) DEFAULT 'free', -- free, pro, enterprise
    subscription_status VARCHAR(50) DEFAULT 'active', -- active, suspended, cancelled
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    is_email_verified BOOLEAN DEFAULT FALSE,
    email_verification_token VARCHAR(255),
    password_reset_token VARCHAR(255),
    password_reset_expires TIMESTAMP
);

-- User sessions (for JWT token management)
CREATE TABLE user_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Organizations (optional: for team/enterprise features)
CREATE TABLE organizations (
    id TEXT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    owner_id TEXT NOT NULL REFERENCES users(id),
    subscription_tier VARCHAR(50) DEFAULT 'free',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Organization members (for team collaboration)
CREATE TABLE organization_members (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(50) DEFAULT 'member', -- owner, admin, member, viewer
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(organization_id, user_id)
);
```

#### Modify Existing Tables for CE User Isolation

Add `user_id` to all tables and enforce filtering in application logic:

```sql
ALTER TABLE domainmodel ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE domainmodelrelationship ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE domainelementproperties ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE canvas_models ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE canvas_element_instances ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE canvas_relationships ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE canvas_property_instances ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE audit_log ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE;

CREATE INDEX idx_domainmodel_user_id ON domainmodel(user_id);
CREATE INDEX idx_domainmodelrelationship_user_id ON domainmodelrelationship(user_id);
CREATE INDEX idx_domainelementproperties_user_id ON domainelementproperties(user_id);
CREATE INDEX idx_canvas_models_user_id ON canvas_models(user_id);
CREATE INDEX idx_canvas_element_instances_user_id ON canvas_element_instances(user_id);
CREATE INDEX idx_canvas_relationships_user_id ON canvas_relationships(user_id);
CREATE INDEX idx_canvas_property_instances_user_id ON canvas_property_instances(user_id);
CREATE INDEX idx_audit_log_user_id ON audit_log(user_id);
```

### 1.2 CE Data Upgrade Script

Create a migration script to:
1. Add `user_id` columns to existing SQLite tables
2. Create a default user for all pre-existing data
3. Backfill `user_id` for all existing records

```python
# migrate_ce_sqlite.py
import sqlite3
import uuid
from datetime import datetime

def migrate_ce_sqlite(sqlite_path, default_user_email):
    conn = sqlite3.connect(sqlite_path)
    cur = conn.cursor()

    user_id = str(uuid.uuid4())
    cur.execute("""
        INSERT INTO users (id, email, password_hash, is_active)
        VALUES (?, ?, ?, ?)
    """, (user_id, default_user_email, 'migrated', True))

    # Backfill user_id across existing tables
    for table in [
        'domainmodel', 'domainmodelrelationship', 'domainelementproperties',
        'canvas_models', 'canvas_element_instances', 'canvas_relationships',
        'canvas_property_instances', 'audit_log'
    ]:
        cur.execute(f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL", (user_id,))

    conn.commit()
    conn.close()
```

---

## Phase 2: Custom Authentication & CE Limits

### 2.1 Authentication System

#### Token Implementation

```python
# auth.py
import jwt
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, g
import bcrypt

SECRET_KEY = os.getenv('AUTH_SECRET_KEY')
TOKEN_EXPIRATION_HOURS = 24

def hash_password(password):
    """Hash a password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password, password_hash):
    """Verify a password against a hash"""
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))

def generate_token(user_id, email):
    """Generate auth token"""
    payload = {
        'user_id': str(user_id),
        'email': email,
        'exp': datetime.utcnow() + timedelta(hours=TOKEN_EXPIRATION_HOURS),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')

def verify_token(token):
    """Verify auth token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def require_auth(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        
        # Check Authorization header
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(' ')[1]  # Bearer <token>
            except IndexError:
                return jsonify({'error': 'Invalid authorization header'}), 401
        
        if not token:
            return jsonify({'error': 'Authentication required'}), 401
        
        payload = verify_token(token)
        if not payload:
            return jsonify({'error': 'Invalid or expired token'}), 401
        
        # Set current user in Flask g
        g.current_user_id = payload['user_id']
        g.current_user_email = payload['email']
        
        return f(*args, **kwargs)
    return decorated_function
```

#### Authentication Endpoints

```python
# routes/auth.py
from flask import Blueprint, request, jsonify, g
from auth import hash_password, verify_password, generate_token
import psycopg2
from psycopg2.extras import RealDictCursor

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/api/auth/register', methods=['POST'])
def register():
    """Register a new user"""
    data = request.json
    email = data.get('email')
    password = data.get('password')
    full_name = data.get('full_name')
    
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Check if user exists
    cur.execute("SELECT id FROM users WHERE email = %s", (email,))
    if cur.fetchone():
        return jsonify({'error': 'User already exists'}), 409
    
    # Create user
    password_hash = hash_password(password)
    cur.execute("""
        INSERT INTO users (email, password_hash, full_name, is_active)
        VALUES (%s, %s, %s, %s)
        RETURNING id, email, full_name
    """, (email, password_hash, full_name, True))
    
    user = cur.fetchone()
    conn.commit()
    
    # Generate token
    token = generate_token(user['id'], user['email'])
    
    return jsonify({
        'token': token,
        'user': {
            'id': str(user['id']),
            'email': user['email'],
            'full_name': user['full_name']
        }
    }), 201

@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    """Login user"""
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT id, email, password_hash, full_name, is_active FROM users WHERE email = %s", (email,))
    user = cur.fetchone()
    
    if not user or not verify_password(password, user['password_hash']):
        return jsonify({'error': 'Invalid credentials'}), 401
    
    if not user['is_active']:
        return jsonify({'error': 'Account is inactive'}), 403
    
    # Update last login
    cur.execute("UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = %s", (user['id'],))
    conn.commit()
    
    # Generate token
    token = generate_token(user['id'], user['email'])
    
    return jsonify({
        'token': token,
        'user': {
            'id': str(user['id']),
            'email': user['email'],
            'full_name': user['full_name']
        }
    }), 200

@auth_bp.route('/api/auth/me', methods=['GET'])
@require_auth
def get_current_user():
    """Get current user info"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT id, email, full_name, company_name, subscription_tier FROM users WHERE id = %s", (g.current_user_id,))
    user = cur.fetchone()
    
    return jsonify({
        'id': str(user['id']),
        'email': user['email'],
        'full_name': user['full_name'],
        'company_name': user['company_name'],
        'subscription_tier': user['subscription_tier']
    }), 200
```

### 2.2 Update All API Endpoints

Modify all existing endpoints to:
1. Require authentication (`@require_auth` decorator)
2. Filter by `user_id`
3. Set `user_id` on create operations
4. Enforce CE limits for models and element occurrences

```python
# Example: Updated get_records endpoint
@app.route('/api/records', methods=['GET'])
@require_auth
def get_records():
    """Get all records for current user"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT * FROM domainmodel 
        WHERE user_id = %s
        ORDER BY created_at DESC
    """, (g.current_user_id,))
    
    records = cur.fetchall()
    return jsonify([dict(record) for record in records]), 200
```

### 2.3 Community Edition Limits

Define hard caps for the CE hosted instance:

```python
# ce_limits.py
CE_LIMITS = {
    'max_models': 5,
    'max_element_occurrences': 200
}

def can_create_model(conn, user_id):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM canvas_models WHERE user_id = ?", (user_id,))
    return cur.fetchone()[0] < CE_LIMITS['max_models']

def can_create_element_occurrence(conn, user_id):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM canvas_element_instances WHERE user_id = ?", (user_id,))
    return cur.fetchone()[0] < CE_LIMITS['max_element_occurrences']
```

---

## Phase 3: SaaS Migration (Full Multi-Tenancy)

### 3.1 Database Connection Management

Replace SQLite connection with PostgreSQL:

```python
# database.py
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
import os

# Connection pool for better performance
pool = ThreadedConnectionPool(
    minconn=1,
    maxconn=20,
    dsn=os.getenv('DATABASE_URL')
)

def get_db_connection():
    """Get database connection from pool"""
    return pool.getconn()

def return_db_connection(conn):
    """Return connection to pool"""
    pool.putconn(conn)

# Context manager for database operations
class DatabaseConnection:
    def __init__(self):
        self.conn = None
    
    def __enter__(self):
        self.conn = get_db_connection()
        return self.conn
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            if exc_type:
                self.conn.rollback()
            else:
                self.conn.commit()
            return_db_connection(self.conn)
```

### 3.2 Environment Configuration

```python
# config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Database
    DATABASE_URL = os.getenv('DATABASE_URL')
    
    # JWT
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
    JWT_ALGORITHM = 'HS256'
    JWT_EXPIRATION_HOURS = 24
    
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY')
    DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    # CORS
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', 'http://localhost:3000').split(',')
    
    # Email (for verification/reset)
    SMTP_HOST = os.getenv('SMTP_HOST')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    SMTP_USER = os.getenv('SMTP_USER')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
    
    # File Storage (for images)
    STORAGE_TYPE = os.getenv('STORAGE_TYPE', 'local')  # local, s3, azure
    AWS_S3_BUCKET = os.getenv('AWS_S3_BUCKET')
    AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
```

### 3.3 Error Handling & Logging

```python
# error_handlers.py
from flask import jsonify
import logging
import traceback

logger = logging.getLogger(__name__)

@app.errorhandler(400)
def bad_request(error):
    return jsonify({'error': 'Bad request', 'message': str(error)}), 400

@app.errorhandler(401)
def unauthorized(error):
    return jsonify({'error': 'Unauthorized', 'message': 'Authentication required'}), 401

@app.errorhandler(403)
def forbidden(error):
    return jsonify({'error': 'Forbidden', 'message': 'Insufficient permissions'}), 403

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found', 'message': str(error)}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal error: {traceback.format_exc()}")
    return jsonify({'error': 'Internal server error', 'message': 'An unexpected error occurred'}), 500
```

---

## Phase 4: Frontend Updates

### 4.1 Authentication UI

Add login/register pages:

```html
<!-- login.html -->
<div id="loginModal" class="auth-modal">
    <div class="auth-container">
        <h2>Login to EDGY Repository Modeller</h2>
        <form id="loginForm">
            <input type="email" id="loginEmail" placeholder="Email" required>
            <input type="password" id="loginPassword" placeholder="Password" required>
            <button type="submit">Login</button>
        </form>
        <p>Don't have an account? <a href="#" onclick="showRegister()">Register</a></p>
    </div>
</div>
```

### 4.2 API Client Updates

Update all API calls to include authentication token:

```javascript
// api.js
const API_BASE_URL = process.env.API_BASE_URL || 'https://api.edygymodeller.com';

class APIClient {
    constructor() {
        this.token = localStorage.getItem('auth_token');
    }
    
    setToken(token) {
        this.token = token;
        localStorage.setItem('auth_token', token);
    }
    
    async request(endpoint, options = {}) {
        const url = `${API_BASE_URL}${endpoint}`;
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };
        
        if (this.token) {
            headers['Authorization'] = `Bearer ${this.token}`;
        }
        
        const response = await fetch(url, {
            ...options,
            headers
        });
        
        if (response.status === 401) {
            // Token expired or invalid
            this.logout();
            window.location.href = '/login';
            return;
        }
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.message || 'Request failed');
        }
        
        return response.json();
    }
    
    async get(endpoint) {
        return this.request(endpoint, { method: 'GET' });
    }
    
    async post(endpoint, data) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }
    
    async put(endpoint, data) {
        return this.request(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }
    
    async delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    }
    
    logout() {
        this.token = null;
        localStorage.removeItem('auth_token');
    }
}

const api = new APIClient();
```

### 4.3 Route Protection

Add route guards to protect authenticated pages:

```javascript
// auth.js
function requireAuth() {
    const token = localStorage.getItem('auth_token');
    if (!token) {
        window.location.href = '/login';
        return false;
    }
    return true;
}

// Check auth on page load
document.addEventListener('DOMContentLoaded', () => {
    if (window.location.pathname !== '/login' && window.location.pathname !== '/register') {
        requireAuth();
    }
});
```

---

## Phase 5: Hosting & Deployment

### 5.0 Community Edition Hosting Recommendation

**Recommended**: Fly.io (free tier) with a single SQLite-backed VM and a small persistent volume.
- **Why**: SQLite requires a persistent disk. Fly.io offers lightweight VMs and supports volumes, making it the simplest way to keep SQLite and stay near-zero cost.
- **Tradeoffs**: Cold starts and resource limits on free tier; upgrade to paid if you need more stable uptime or storage.

**Alternatives**:
- **Render/Railway**: Easiest UI/CI flow, but verify persistent disk support on free tier (SQLite will lose data on ephemeral filesystems).
- **Always-Free VM (Oracle/AWS Free Tier)**: Most control and true persistence, but more ops work.

### 5.1 Hosting Options

#### Option A: Platform-as-a-Service (Easiest)

**Heroku**
- Pros: Easy deployment, automatic scaling, PostgreSQL addon
- Cons: Can be expensive at scale
- Cost: ~$7-25/month for basic setup

**Railway**
- Pros: Modern, good pricing, easy PostgreSQL
- Cons: Newer platform
- Cost: ~$5-20/month

**Render**
- Pros: Free tier available, easy setup
- Cons: Slower on free tier, cold starts
- Cost: Free tier available, $7+/month for production

#### Option B: Infrastructure-as-a-Service (More Control)

**AWS (EC2 + RDS)**
- Pros: Scalable, reliable, many services
- Cons: Complex setup, can be expensive
- Cost: ~$20-100+/month

**DigitalOcean**
- Pros: Simple, predictable pricing
- Cons: Less managed services
- Cost: ~$12-48/month

**Azure App Service**
- Pros: Good integration, managed services
- Cons: Can be complex
- Cost: ~$13-55/month

### 5.2 Deployment Configuration

#### Docker Setup

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose port
EXPOSE 5000

# Run application
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "server:app"]
```

#### Docker Compose (for local development)

```yaml
# docker-compose.yml
version: '3.8'

services:
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: edgy_repo
      POSTGRES_USER: edgy_user
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  web:
    build: .
    command: gunicorn --bind 0.0.0.0:5000 --workers 4 server:app
    volumes:
      - .:/app
    ports:
      - "5000:5000"
    environment:
      DATABASE_URL: postgresql://edgy_user:${DB_PASSWORD}@db:5432/edgy_repo
      JWT_SECRET_KEY: ${JWT_SECRET_KEY}
    depends_on:
      - db

volumes:
  postgres_data:
```

### 5.3 CI/CD Pipeline

```yaml
# .github/workflows/deploy.yml
name: Deploy to Production

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      
      - name: Run tests
        run: |
          pytest tests/
      
      - name: Deploy to Heroku
        uses: akhileshns/heroku-deploy@v3.12.12
        with:
          heroku_api_key: ${{secrets.HEROKU_API_KEY}}
          heroku_app_name: "edgy-repo-modeller"
          heroku_email: "your-email@example.com"
```

---

## Phase 6: Security Considerations

### 6.1 Security Best Practices

1. **Password Security**
   - Use bcrypt with salt rounds ≥ 12
   - Enforce password complexity requirements
   - Implement password reset flow with time-limited tokens

2. **API Security**
   - Rate limiting (e.g., 100 requests/minute per user)
   - CORS configuration
   - Input validation and sanitization
   - SQL injection prevention (use parameterized queries)

3. **Data Protection**
   - Encrypt sensitive data at rest
   - Use HTTPS for all communications
   - Implement CSRF protection
   - Regular security audits

4. **Monitoring**
   - Log all authentication attempts
   - Monitor for suspicious activity
   - Set up alerts for failed logins

### 6.2 Rate Limiting

```python
# rate_limiting.py
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import g

limiter = Limiter(
    app,
    key_func=lambda: g.current_user_id if hasattr(g, 'current_user_id') else get_remote_address(),
    default_limits=["200 per day", "50 per hour"]
)

# Apply to specific endpoints
@app.route('/api/records', methods=['GET'])
@require_auth
@limiter.limit("100 per minute")
def get_records():
    # ...
```

---

## Phase 7: Subscription & Billing

### 7.1 Subscription Tiers

```python
# subscription_tiers.py
SUBSCRIPTION_TIERS = {
    'free': {
        'max_elements': 50,
        'max_models': 5,
        'max_properties': 100,
        'features': ['basic_modeling', 'basic_analytics']
    },
    'pro': {
        'max_elements': 500,
        'max_models': 50,
        'max_properties': 1000,
        'features': ['advanced_modeling', 'advanced_analytics', 'export', 'api_access']
    },
    'enterprise': {
        'max_elements': -1,  # Unlimited
        'max_models': -1,
        'max_properties': -1,
        'features': ['all_features', 'team_collaboration', 'custom_integrations', 'priority_support']
    }
}

def check_subscription_limit(user_id, resource_type, current_count):
    """Check if user has reached subscription limit"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT subscription_tier FROM users WHERE id = %s", (user_id,))
    tier = cur.fetchone()[0]
    
    limits = SUBSCRIPTION_TIERS.get(tier, SUBSCRIPTION_TIERS['free'])
    max_allowed = limits.get(f'max_{resource_type}', 0)
    
    if max_allowed == -1:
        return True  # Unlimited
    
    return current_count < max_allowed
```

### 7.2 Payment Integration

**Stripe Integration** (Recommended)

```python
# billing.py
import stripe

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

def create_checkout_session(user_id, tier):
    """Create Stripe checkout session"""
    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'usd',
                'product_data': {
                    'name': f'EDGY {tier.capitalize()} Plan',
                },
                'unit_amount': get_tier_price(tier),
            },
            'quantity': 1,
        }],
        mode='subscription',
        success_url=f'{FRONTEND_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}',
        cancel_url=f'{FRONTEND_URL}/billing/cancel',
        metadata={'user_id': str(user_id), 'tier': tier}
    )
    return session
```

---

## Phase 8: Migration Timeline

### Weeks 1-3: Community Edition (Hosted Trial)
- [ ] Add users and sessions tables (SQLite)
- [ ] Add `user_id` to all tables and backfill existing data
- [ ] Implement custom auth (register/login/me)
- [ ] Enforce CE limits (models + element occurrences)
- [ ] Deploy to free hosting for select/trial users

### Weeks 4-8: SaaS Foundations
- [ ] Migrate to PostgreSQL
- [ ] Add organization tables and tenant isolation
- [ ] Implement JWT auth + OAuth2 support
- [ ] Update all API endpoints for org tenancy

### Weeks 9-12: SaaS Deployment
- [ ] Production hosting
- [ ] Monitoring, backups, and security hardening
- [ ] Beta with early adopters
- [ ] Launch prep

---

## Phase 9: Cost Estimates

### Development Costs
- **Backend Development**: 40-80 hours @ $50-100/hour = $2,000-8,000
- **Frontend Updates**: 20-40 hours @ $50-100/hour = $1,000-4,000
- **Database Migration**: 10-20 hours @ $50-100/hour = $500-2,000
- **Testing & QA**: 20-40 hours @ $50-100/hour = $1,000-4,000
- **Total Development**: $4,500-18,000

### Monthly Operating Costs (Community Edition)
- **Hosting (Render/Railway Free)**: $0/month
- **SQLite**: $0/month
- **Domain**: $1-2/month
- **SSL Certificate**: $0 (Let's Encrypt free)
- **Email Service (SendGrid)**: $0-15/month
- **Monitoring (Sentry)**: $0-26/month (free tier available)
-- **Total Monthly**: $1-43/month

### Monthly Operating Costs (Small Scale SaaS)
- **Hosting (Heroku/Railway)**: $7-25/month
- **PostgreSQL Database**: $0-20/month (included or separate)
- **Domain**: $1-2/month
- **SSL Certificate**: $0 (Let's Encrypt free)
- **Email Service (SendGrid)**: $0-15/month
- **Monitoring (Sentry)**: $0-26/month (free tier available)
- **Total Monthly**: $8-88/month

### Monthly Operating Costs (Medium Scale - 100 users)
- **Hosting**: $25-100/month
- **Database**: $20-50/month
- **CDN (CloudFlare)**: $0-20/month
- **Email Service**: $15-50/month
- **Monitoring**: $26-100/month
- **Total Monthly**: $86-320/month

---

## Phase 10: Additional Considerations

### 10.1 Data Backup & Recovery
- Automated daily backups
- Point-in-time recovery
- Backup retention policy (30-90 days)

### 10.2 Compliance
- GDPR compliance (if serving EU users)
- Data retention policies
- User data export functionality
- User data deletion (right to be forgotten)

### 10.3 Scalability
- Database connection pooling
- Caching layer (Redis)
- CDN for static assets
- Load balancing (if needed)

### 10.4 Monitoring & Analytics
- Application performance monitoring (APM)
- Error tracking (Sentry)
- User analytics
- Business metrics dashboard

---

## Next Steps

1. **Review this plan** and adjust limits/CE scope
2. **Choose free hosting platform** (Render or Railway)
3. **Implement CE auth + limits** (Phase 1-2)
4. **Launch CE trial** with select users
5. **Begin SaaS migration** after CE feedback

---

## Resources

- **PostgreSQL Documentation**: https://www.postgresql.org/docs/
- **Flask Authentication**: https://flask.palletsprojects.com/en/2.3.x/patterns/authentication/
- **JWT Best Practices**: https://jwt.io/introduction
- **Heroku Deployment**: https://devcenter.heroku.com/articles/getting-started-with-python
- **Railway Deployment**: https://docs.railway.app/
- **Stripe Integration**: https://stripe.com/docs/payments/checkout

---

**Document Version**: 1.0  
**Last Updated**: 2024  
**Author**: AI Assistant  
**Status**: Draft - Ready for Review

