#!/usr/bin/env python3
"""
Script to merge all Statscore documentation pages into a single HTML file
suitable for printing to PDF.
"""
import os
import re
from pathlib import Path

# Directory containing the docs
DOCS_DIR = Path("statscore_docs")
OUTPUT_FILE = "statscore_complete_docs.html"

# Order of files to merge
FILES_ORDER = [
    # 1. Developer Guide
    "01_developer_guide.html",
    "02_amqp_service.html",
    "03_messages_types.html",
    "04_message_incident.html",
    "05_message_event.html",
    "06_message_event_keep_alive.html",
    "07_message_events_lineups.html",
    "08_interrupted_live_data_feed.html",
    "09_handling_key_incidents_confirmations.html",
    "10_handling_incident_attributes.html",
    "11_api_service.html",
    "12_sports_data_structure.html",
    "13_help_support.html",
    
    # 2. API Resources
    "api_00_resources.html",
    "api_01_booked_events_create.html",
    "api_02_booked_events_delete.html",
    "api_03_events_show.html",
    "api_04_events_index.html",
    "api_05_booked_events_index.html",
    "api_06_feed_index.html",
    "api_07_feed_show.html",
    "api_08_incidents_index.html",
    "api_09_logo_index.html",
    "api_10_reports_clients_events_index.html",
    "api_11_skins_index.html",
    "api_12_sports_index.html",
    "api_13_sports_show.html",
    "api_14_statuses_index.html",
    "api_15_events_sub_participants_index.html",
    "api_16_feed_examples.html",
    
    # 3. Booking Events
    "booking_events_via_api.html",
    
    # 4. Additional Pages
    "extra_01_api_feed_examples.html",
    "extra_02_sports_data_structure.html",
    "extra_03_statuses.html",
    "extra_04_results.html",
    "extra_05_statistics.html",
    "extra_06_event_details.html",
    "extra_07_incidents.html",
    
    # 5. Feed Examples Sub-pages
    "extra_08_areas_index_example.html",
    "extra_09_booked_events_index_example.html",
    "extra_10_competitions_index_example.html",
    "extra_11_competitions_show_example.html",
    "extra_12_events_index_example.html",
    "extra_13_events_show_example.html",
    "extra_14_feed_index_example.html",
    "extra_15_feed_show_example.html",
    "extra_16_incidents_index_example.html",
    "extra_17_languages_index_example.html",
    
    # 6. User Guide
    "user_guide_00_main.html",
    "user_guide_01_types_of_coverage.html",
    "user_guide_02_booking_the_events.html",
    "user_guide_03_trader_view.html",
    "user_guide_04_incident_message.html",
    "user_guide_05_event_message.html",
    "user_guide_06_key_incidents_confirmation.html",
    "user_guide_07_incident_attributes.html",
    "user_guide_08_lineups_formations.html",
    "user_guide_09_markets_managing.html",
    "user_guide_10_emergency_incidents.html",
    "user_guide_11_splitted_statistics.html",
    "user_guide_12_var_soccer.html",
    "user_guide_13_expected_goals.html",
    "user_guide_14_player_ratings.html",
    "user_guide_15_faq.html"
]

def extract_content(html_content):
    """
    Extract the main content from the HTML file.
    This is a simple regex-based extractor tailored for Confluence exports/pages.
    """
    # Try to find the main content div usually found in Confluence pages
    # This is a heuristic and might need adjustment based on actual page structure
    
    # Look for the main content area
    # Pattern 1: <div id="main-content" ...> ... </div>
    match = re.search(r'<div[^>]*id=["\']main-content["\'][^>]*>(.*?)</div>\s*<div[^>]*id=["\']footer["\']', html_content, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1)
        
    # Pattern 2: <div id="content" ...> ... </div>
    match = re.search(r'<div[^>]*id=["\']content["\'][^>]*>(.*?)</div>\s*<div[^>]*id=["\']footer["\']', html_content, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1)

    # Fallback: Just return the body content
    match = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1)
        
    return html_content

def main():
    print(f"Merging {len(FILES_ORDER)} files into {OUTPUT_FILE}...")
    
    full_content = []
    
    # Header
    full_content.append("""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Statscore ScoutsFeed Documentation</title>
        <style>
            body { 
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                line-height: 1.6;
                max-width: 1000px;
                margin: 0 auto;
                padding: 20px;
                color: #333;
            }
            h1, h2, h3 { color: #2c3e50; }
            h1 { border-bottom: 2px solid #eee; padding-bottom: 10px; margin-top: 50px; }
            code { background: #f4f4f4; padding: 2px 5px; border-radius: 3px; font-family: monospace; }
            pre { background: #f4f4f4; padding: 15px; border-radius: 5px; overflow-x: auto; }
            .page-break { page-break-before: always; margin-top: 50px; border-top: 1px dashed #ccc; padding-top: 20px; }
            img { max-width: 100%; height: auto; }
            table { border-collapse: collapse; width: 100%; margin: 20px 0; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; }
            
            /* Hide sidebar and navigation elements if they leaked through */
            .aui-sidebar, .aui-header, #navigation, .ia-fixed-sidebar, nav { display: none !important; }
        </style>
    </head>
    <body>
        <div style="text-align: center; margin-bottom: 100px; margin-top: 50px;">
            <h1 style="font-size: 48px; border: none;">Statscore ScoutsFeed</h1>
            <h2 style="font-size: 32px; color: #666;">Developer Documentation</h2>
            <p>Generated on: 2025-12-01</p>
        </div>
        
        <div class="toc">
            <h2>Table of Contents</h2>
            <ul>
    """)
    
    # Generate TOC
    for filename in FILES_ORDER:
        title = filename.replace('.html', '').replace('_', ' ').title()
        # Remove prefixes like "01 ", "Api 00 ", "Extra 01 "
        title = re.sub(r'^\d+\s+', '', title)
        title = re.sub(r'^Api\s+\d+\s+', '', title)
        title = re.sub(r'^Extra\s+\d+\s+', '', title)
        title = re.sub(r'^User\s+Guide\s+\d+\s+', '', title)
        
        full_content.append(f'<li><a href="#{filename}">{title}</a></li>')
        
    full_content.append("""
            </ul>
        </div>
        <div class="page-break"></div>
    """)
    
    # Merge Content
    for filename in FILES_ORDER:
        file_path = DOCS_DIR / filename
        if not file_path.exists():
            print(f"Warning: File not found {filename}")
            continue
            
        print(f"Processing {filename}...")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Extract body/main content
        extracted = extract_content(content)
        
        # Add an anchor for TOC
        full_content.append(f'<div id="{filename}" class="page-break">')
        full_content.append(extracted)
        full_content.append('</div>')
        
    # Footer
    full_content.append("""
    </body>
    </html>
    """)
    
    # Write output
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(full_content))
        
    print(f"\nSuccessfully created {OUTPUT_FILE}")
    print(f"Total size: {os.path.getsize(OUTPUT_FILE) / 1024 / 1024:.2f} MB")

if __name__ == "__main__":
    main()
