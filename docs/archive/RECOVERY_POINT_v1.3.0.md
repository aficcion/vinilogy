# Recovery Point v1.3.0

**Created:** 2025-12-03 20:35 CET  
**Git Tag:** `v1.3.0`  
**Database Backup:** `backups/vinylbe.db.backup_v1.3.0`

## What's Included

This recovery point captures the state **before** implementing guest-to-Last.fm profile merge functionality.

### Features in v1.3.0
- ✅ Unified search for artists and albums
- ✅ Album add functionality with guest user support
- ✅ Fixed CSS layout for album cards (separate grid containers)
- ✅ Fixed JSON parse error with HTML entity escaping
- ✅ Improved visual feedback for added albums

### What's NOT Included
- ❌ Guest profile merge when connecting to Last.fm
- ❌ Manually added albums sync to Last.fm user

## How to Restore

### Quick Restore (Automated)
```bash
./restore_v1.3.0.sh
```

### Manual Restore

1. **Stop services:**
   ```bash
   pkill -f start_services.py
   ```

2. **Restore database:**
   ```bash
   cp backups/vinylbe.db.backup_v1.3.0 vinylbe.db
   ```

3. **Checkout git tag:**
   ```bash
   git checkout v1.3.0
   ```

4. **Restart services:**
   ```bash
   python3 start_services.py
   ```

## Next Steps After Restore

If you restore to this point, you'll need to re-implement:
- Guest profile merge functionality
- Manually added albums sync
