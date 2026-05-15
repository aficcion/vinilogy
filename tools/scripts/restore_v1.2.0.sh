#!/bin/bash

# Restoration Script v1.2.0
# Restores code and database to the state before album search integration

echo "⚠️  Starting restoration to v1.2.0..."

# 1. Stop services
echo "Stopping services..."
pkill -f start_services.py || true

# 2. Restore Database
if [ -f "backups/vinylbe.db.backup_v1.2.0" ]; then
    echo "Restoring database from backups/vinylbe.db.backup_v1.2.0..."
    cp backups/vinylbe.db.backup_v1.2.0 vinylbe.db
else
    echo "❌ Database backup not found!"
    exit 1
fi

# 3. Restore Code
echo "Restoring code to git tag v1.2.0..."
git checkout v1.2.0

echo "✅ Restoration complete!"
echo "Run 'python3 start_services.py' to restart the application."
