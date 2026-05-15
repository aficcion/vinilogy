#!/bin/bash
# Restoration script for v1.1.0 - Discogs Fallback System
# Created: 2025-12-03

set -e

echo "=========================================="
echo "Vinylbe Recovery Point v1.1.0"
echo "=========================================="
echo ""

# Check if we're in the right directory
if [ ! -f "vinylbe.db" ]; then
    echo "❌ Error: vinylbe.db not found. Are you in the project root?"
    exit 1
fi

echo "⚠️  WARNING: This will restore the application to v1.1.0"
echo "   - Code will be restored from git tag"
echo "   - Database can optionally be restored from backup"
echo ""

read -p "Continue? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "❌ Restoration cancelled"
    exit 0
fi

echo ""
echo "1️⃣  Stopping services..."
pkill -f start_services.py || true
sleep 2

echo ""
echo "2️⃣  Restoring code from git tag v1.1.0-discogs-fallback..."
git checkout v1.1.0-discogs-fallback

echo ""
read -p "Do you want to restore the database? (yes/no): " restore_db
if [ "$restore_db" = "yes" ]; then
    echo "3️⃣  Backing up current database..."
    cp vinylbe.db vinylbe.db.backup_$(date +%Y%m%d_%H%M%S)
    
    echo "4️⃣  Restoring database from recovery point..."
    # Find the most recent backup from this recovery point
    latest_backup=$(ls -t recovery_points/vinylbe_20251203_*.db 2>/dev/null | head -n1)
    
    if [ -z "$latest_backup" ]; then
        echo "❌ No database backup found for this recovery point"
        exit 1
    fi
    
    cp "$latest_backup" vinylbe.db
    echo "✅ Database restored from: $latest_backup"
else
    echo "3️⃣  Skipping database restoration"
fi

echo ""
echo "5️⃣  Starting services..."
python3 start_services.py &
sleep 5

echo ""
echo "=========================================="
echo "✅ Restoration Complete!"
echo "=========================================="
echo ""
echo "Services should now be running at:"
echo "  - Gateway: http://localhost:5000"
echo "  - Recommender: http://localhost:3002"
echo "  - Discogs: http://localhost:3001"
echo ""
echo "Check RECOVERY_POINT_v1.1.0.md for details"
echo ""
