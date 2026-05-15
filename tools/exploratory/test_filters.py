import sqlite3
import json

conn = sqlite3.connect('vinylbe.db')
cursor = conn.cursor()

cursor.execute("SELECT title, release_data, release_type FROM user_collection_discogs LIMIT 100")
rows = cursor.fetchall()

candidates = []
excluded = 0
total = 0

print("Analying simplified logic...")

for row in rows:
    total += 1
    title = row[0]
    data = json.loads(row[1])
    
    basic_info = data.get("basic_information", {})
    formats = [f.get("name", "") for f in basic_info.get("formats", [])]
    descriptions = []
    for f in basic_info.get("formats", []):
        descriptions.extend(f.get("descriptions", []))
    
    full_format_list = formats + descriptions
    full_formats_lower = [f.lower() for f in full_format_list]
    
    # Logic from main.py
    excluded_types = ["single", "maxi-single", "ep", "mini-album", "compilation"]
    is_excluded = any(d in excluded_types for d in full_formats_lower) # simplified matching
    
    # Check basic format string
    if "single" in [f.lower() for f in formats] or "compilation" in [f.lower() for f in formats]:
        is_excluded = True
        
    has_vinyl = any("vinyl" in f or "lp" in f for f in full_formats_lower)
    
    if is_excluded:
        excluded += 1
        # print(f"Excluded: {title} ({full_formats_lower})")
    elif not has_vinyl:
        candidates.append(f"{title} ({full_formats_lower})")

print(f"Total: {total}")
print(f"Excluded: {excluded}")
print(f"Candidates kept: {len(candidates)}")
for c in candidates[:10]:
    print(f" - {c}")

conn.close()
