#!/bin/sh
# This script ensures the database is initialized before starting the server.

# Navigate to the app directory
cd /app

# Run the database initialization command using Flask's CLI
flask initdb
echo "Database initialization complete."

# Start the Gunicorn server
echo "Starting Gunicorn..."
# THE FIX: Added --forwarded-allow-ips="*" to trust proxy headers
exec gunicorn --workers 3 --bind 0.0.0.0:5000 --forwarded-allow-ips="*" app:app
