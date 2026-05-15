#!/usr/bin/env python3
"""
View Recommendation Generation Logs
Utility script to view and analyze recommendation generation logs.
"""
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from gateway import recommendation_logger


def print_header(title):
    """Print a formatted header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def view_recent_logs(limit=20):
    """View the most recent log entries."""
    print_header(f"ÚLTIMAS {limit} RECOMENDACIONES GENERADAS")
    
    logs = recommendation_logger.get_recent_logs(limit)
    
    if not logs:
        print("No hay logs disponibles.")
        return
    
    for i, log in enumerate(reversed(logs), 1):
        timestamp = datetime.fromisoformat(log["timestamp"])
        print(f"{i}. [{timestamp.strftime('%Y-%m-%d %H:%M:%S')}] User {log['user_id']}")
        print(f"   Artista: {log['artist_name']}")
        print(f"   Fuente: {log['source'].upper()}")
        print(f"   Recomendaciones: {log['recommendations_count']}")
        
        if log.get("metadata"):
            print(f"   Metadata: {log['metadata']}")
        
        print()


def view_stats(days=7):
    """View statistics for the last N days."""
    print_header(f"ESTADÍSTICAS DE LOS ÚLTIMOS {days} DÍAS")
    
    stats = recommendation_logger.get_stats_summary(days)
    
    if "error" in stats:
        print(stats["error"])
        return
    
    print(f"Total de recomendaciones: {stats['total_recommendations']}")
    print(f"  - Canonical (Discogs/MusicBrainz): {stats['total_canonical']}")
    print(f"  - Spotify: {stats['total_spotify']}")
    print()
    
    if stats.get("daily_breakdown"):
        print("Desglose diario:")
        print("-" * 80)
        for day in reversed(stats["daily_breakdown"]):
            print(f"{day['date']}: {day.get('total_recommendations', 0)} total "
                  f"(Canonical: {day.get('canonical_recommendations', 0)}, "
                  f"Spotify: {day.get('spotify_recommendations', 0)})")


def view_last_30_minutes():
    """View logs from the last 30 minutes."""
    print_header("RECOMENDACIONES DE LOS ÚLTIMOS 30 MINUTOS")
    
    now = datetime.utcnow()
    start_time = now - timedelta(minutes=30)
    
    logs = recommendation_logger.get_logs_by_timerange(start_time, now)
    
    if not logs:
        print("No hay recomendaciones generadas en los últimos 30 minutos.")
        return
    
    # Aggregate stats
    total_recs = 0
    canonical_count = 0
    spotify_count = 0
    artists_processed = set()
    
    for log in logs:
        total_recs += log["recommendations_count"]
        artists_processed.add(log["artist_name"])
        
        if log["source"] == "canonical":
            canonical_count += log["recommendations_count"]
        elif log["source"] == "spotify":
            spotify_count += log["recommendations_count"]
    
    print(f"Total de recomendaciones generadas: {total_recs}")
    print(f"  - Canonical: {canonical_count}")
    print(f"  - Spotify: {spotify_count}")
    print(f"\nArtistas procesados: {len(artists_processed)}")
    print(f"Artistas: {', '.join(sorted(artists_processed))}")
    print()
    
    # Show individual entries
    print("Detalle:")
    print("-" * 80)
    for log in logs:
        timestamp = datetime.fromisoformat(log["timestamp"])
        print(f"[{timestamp.strftime('%H:%M:%S')}] {log['artist_name']} "
              f"({log['source']}) → {log['recommendations_count']} recs")


def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "recent":
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
            view_recent_logs(limit)
        elif command == "stats":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
            view_stats(days)
        elif command == "30min":
            view_last_30_minutes()
        else:
            print("Comandos disponibles:")
            print("  recent [N]  - Ver las últimas N recomendaciones (default: 20)")
            print("  stats [N]   - Ver estadísticas de los últimos N días (default: 7)")
            print("  30min       - Ver recomendaciones de los últimos 30 minutos")
    else:
        # Default: show last 30 minutes
        view_last_30_minutes()


if __name__ == "__main__":
    main()
