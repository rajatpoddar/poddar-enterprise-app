#!/bin/sh
# This script ensures the database is initialized before starting the server.

# Navigate to the app directory
cd /app

# --- FIX: Only initialize the database if it doesn't exist ---
DB_FILE="/app/data/business.db"
if [ ! -f "$DB_FILE" ]; then
    echo "Database not found. Initializing..."
    flask initdb
    echo "Database initialization complete."
else
    echo "Database already exists. Skipping initialization."
fi

# Start the Gunicorn server
echo "Starting Gunicorn..."
# THE FIX: Added --forwarded-allow-ips="*" to trust proxy headers
exec gunicorn --workers 3 --bind 0.0.0.0:5000 --forwarded-allow-ips="*" app:app
