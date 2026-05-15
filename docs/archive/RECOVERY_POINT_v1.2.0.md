# Recovery Point v1.2.0

**Date:** 2025-12-03
**Description:** Checkpoint before implementing album search integration.
**Git Tag:** `v1.2.0`
**Database Backup:** `backups/vinylbe.db.backup_v1.2.0`

## Restoration Instructions

To restore the system to this state:

1. **Stop all services:**
   ```bash
   pkill -f start_services.py
   ```

2. **Run the restoration script:**
   ```bash
   ./restore_v1.2.0.sh
   ```

3. **Restart services:**
   ```bash
   python3 start_services.py
   ```

## Manual Restoration Steps

If the script fails, you can restore manually:

1. Revert code to tag:
   ```bash
   git checkout v1.2.0
   ```

2. Restore database:
   ```bash
   cp backups/vinylbe.db.backup_v1.2.0 vinylbe.db
   ```
