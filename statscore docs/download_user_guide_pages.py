#!/usr/bin/env python3
"""
Script to download Statscore User Guide and its subpages
"""
import requests
import time
from pathlib import Path
from urllib.parse import urljoin

# Base URL for the Confluence wiki
BASE_URL = "https://statscore.atlassian.net"

# List of all pages to download (path, filename, description)
PAGES = [
    ("/wiki/spaces/SCOUT/pages/6983355/User+guide", "user_guide_00_main.html", "User guide"),
    ("/wiki/spaces/SCOUT/pages/1805287489/Types+of+coverage", "user_guide_01_types_of_coverage.html", "Types of coverage"),
    ("/wiki/spaces/SCOUT/pages/6983168/Booking+the+events", "user_guide_02_booking_the_events.html", "Booking the events"),
    ("/wiki/spaces/SCOUT/pages/6983146/Trader+view", "user_guide_03_trader_view.html", "Trader view"),
    ("/wiki/spaces/SCOUT/pages/4407230495/The+Incident+message+-+key+informations", "user_guide_04_incident_message.html", "The \"Incident\" message - key informations"),
    ("/wiki/spaces/SCOUT/pages/4408410114/The+Event+message+-+key+informations", "user_guide_05_event_message.html", "The \"Event\" message - key informations"),
    ("/wiki/spaces/SCOUT/pages/1805942805/Key+incidents+confirmation", "user_guide_06_key_incidents_confirmation.html", "Key incidents confirmation"),
    ("/wiki/spaces/SCOUT/pages/1805746206/Incident+attributes", "user_guide_07_incident_attributes.html", "Incident attributes"),
    ("/wiki/spaces/SCOUT/pages/4202758148/Lineups+formations+and+appearances", "user_guide_08_lineups_formations.html", "Lineups, formations and appearances"),
    ("/wiki/spaces/SCOUT/pages/4407590914/Markets+managing+-+Betstop+Betstart+functionality", "user_guide_09_markets_managing.html", "Markets managing - Betstop/Betstart functionality"),
    ("/wiki/spaces/SCOUT/pages/3985702918/Emergency+incidents", "user_guide_10_emergency_incidents.html", "Emergency incidents"),
    ("/wiki/spaces/SCOUT/pages/4282155027/Splitted+statistics+for+specific+period+of+the+game", "user_guide_11_splitted_statistics.html", "Splitted statistics for specific period of the game"),
    ("/wiki/spaces/SCOUT/pages/4762009682/Video+Assistant+Referee+VAR+-+soccer", "user_guide_12_var_soccer.html", "Video Assistant Referee (VAR) - soccer"),
    ("/wiki/spaces/SCOUT/pages/4812177415/Expected+Goals+for+soccer", "user_guide_13_expected_goals.html", "Expected Goals for soccer"),
    ("/wiki/spaces/SCOUT/pages/4845928468/Player+Ratings+for+soccer", "user_guide_14_player_ratings.html", "Player Ratings for soccer"),
    ("/wiki/spaces/SCOUT/pages/4396122126/FAQ+-+ScoutsFeed", "user_guide_15_faq.html", "FAQ - ScoutsFeed"),
]

def download_page(url, filename, description, output_dir):
    """Download a single page and save it to a file"""
    full_url = urljoin(BASE_URL, url)
    print(f"Downloading: {description}")
    print(f"  URL: {full_url}")
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(full_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Save the HTML content
        output_path = output_dir / filename
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(response.text)
        
        print(f"  ✓ Saved to: {output_path}")
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def main():
    # Create output directory
    output_dir = Path("statscore_docs")
    output_dir.mkdir(exist_ok=True)
    
    print(f"Starting download of {len(PAGES)} User Guide pages...")
    print(f"Output directory: {output_dir.absolute()}\n")
    print("="*70)
    
    successful = 0
    failed = 0
    
    for url, filename, description in PAGES:
        if download_page(url, filename, description, output_dir):
            successful += 1
        else:
            failed += 1
        
        print("-"*70)
        # Be polite to the server
        time.sleep(1)
    
    print(f"\n{'='*70}")
    print(f"Download complete!")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Total: {len(PAGES)}")
    print(f"{'='*70}")
    
    # Update the index file
    index_path = output_dir / "index.md"
    with open(index_path, 'a', encoding='utf-8') as f:
        f.write("\n\n---\n\n")
        f.write("## User Guide Pages\n\n")
        for i, (url, filename, description) in enumerate(PAGES, 1):
            f.write(f"{i}. [{description}]({filename})\n")
    
    print(f"\nIndex file updated: {index_path}")

if __name__ == "__main__":
    main()
