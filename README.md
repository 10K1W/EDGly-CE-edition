# DomainModel Records Manager

A simple web UI for managing records in your Neon database DomainModel table.

## Setup

1. Install dependencies:
```bash
npm install
```

2. The database connection is already configured in `.env` file. If you need to change it, edit the `.env` file.

3. Start the server:
```bash
npm start
```

4. Open your browser and navigate to:
```
http://localhost:3000
```

## Features

- ✅ Add new records with all fields (name, description, enterprise, facet, element)
- ✅ View all existing records
- ✅ Delete records
- ✅ Modern, responsive UI
- ✅ Real-time feedback

## API Endpoints

- `GET /api/records` - Get all records
- `POST /api/records` - Add a new record
- `DELETE /api/records/:id` - Delete a record

## Database Schema

The DomainModel table includes:
- `id` - Primary key (auto-increment)
- `name` - VARCHAR(255)
- `description` - TEXT
- `enterprise` - VARCHAR(255)
- `facet` - VARCHAR(255)
- `element` - VARCHAR(255)
- `created_at` - TIMESTAMP
- `updated_at` - TIMESTAMP

