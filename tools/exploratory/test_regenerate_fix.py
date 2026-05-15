#!/usr/bin/env python3
"""
Test script to verify the regenerate_recommendations fix.
Tests that invalid source values are properly sanitized.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gateway import db

# Initialize DB
db.init_db()

# Test data with various source values
test_user_id = 999  # Use a test user ID

# Create test user if doesn't exist
conn = db.get_connection()
try:
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO user (id, display_name) VALUES (?, ?)", (test_user_id, "Test User"))
    conn.commit()
finally:
    conn.close()

# Test recommendations with different source values
test_recs = [
    {
        "artist_name": "Test Artist 1",
        "album_name": "Test Album 1",
        "source": "artist_based"  # Should be converted to 'manual'
    },
    {
        "artist_name": "Test Artist 2",
        "album_name": "Test Album 2",
        "source": "lastfm"  # Should remain 'lastfm'
    },
    {
        "artist_name": "Test Artist 3",
        "album_name": "Test Album 3",
        "source": "manual"  # Should remain 'manual'
    },
    {
        "artist_name": "Test Artist 4",
        "album_name": "Test Album 4",
        "source": "invalid_source"  # Should be converted to 'mixed'
    },
    {
        "artist_name": "Test Artist 5",
        "album_name": "Test Album 5",
        "source": "mixed"  # Should remain 'mixed'
    }
]

print("Testing regenerate_recommendations with various source values...")
print("=" * 60)

try:
    # Call regenerate_recommendations
    db.regenerate_recommendations(test_user_id, test_recs)
    print("✓ regenerate_recommendations completed without errors")
    
    # Verify the results
    recommendations = db.get_recommendations_for_user(test_user_id)
    
    print(f"\n✓ Retrieved {len(recommendations)} recommendations")
    print("\nVerifying source field sanitization:")
    print("-" * 60)
    
    expected_sources = {
        "Test Album 1": "manual",    # artist_based → manual
        "Test Album 2": "lastfm",    # lastfm → lastfm
        "Test Album 3": "manual",    # manual → manual
        "Test Album 4": "mixed",     # invalid_source → mixed
        "Test Album 5": "mixed"      # mixed → mixed
    }
    
    all_correct = True
    for rec in recommendations:
        album = rec.get("album_title")
        source = rec.get("source")
        expected = expected_sources.get(album)
        
        if expected:
            status = "✓" if source == expected else "✗"
            if source != expected:
                all_correct = False
            print(f"{status} {album}: source='{source}' (expected: '{expected}')")
    
    # Cleanup
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM recommendation WHERE user_id = ?", (test_user_id,))
        cur.execute("DELETE FROM user WHERE id = ?", (test_user_id,))
        conn.commit()
        print("\n✓ Cleanup completed")
    finally:
        conn.close()
    
    print("\n" + "=" * 60)
    if all_correct:
        print("✓ ALL TESTS PASSED - Source sanitization working correctly!")
        sys.exit(0)
    else:
        print("✗ SOME TESTS FAILED - Check output above")
        sys.exit(1)
        
except Exception as e:
    print(f"\n✗ ERROR: {e}")
    import traceback
    traceback.print_exc()
    
    # Cleanup on error
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM recommendation WHERE user_id = ?", (test_user_id,))
        cur.execute("DELETE FROM user WHERE id = ?", (test_user_id,))
        conn.commit()
        conn.close()
    except:
        pass
    
    sys.exit(1)
