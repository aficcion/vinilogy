#!/bin/bash
# Restore script for Vinylbe v1.3.0
# This script restores the application to the state before implementing guest-to-lastfm merge

echo "🔄 Restoring Vinylbe to v1.3.0..."

# Stop services
echo "Stopping services..."
pkill -f start_services.py

# Restore database
echo "Restoring database..."
cp backups/vinylbe.db.backup_v1.3.0 vinylbe.db

# Checkout git tag
echo "Checking out git tag v1.3.0..."
git checkout v1.3.0

echo "✅ Restore complete!"
echo "To restart services, run: python3 start_services.py"
