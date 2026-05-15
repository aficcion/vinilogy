#!/usr/bin/env python3
"""
Script to check cache statistics from the Recommender Service.
Since logs go to stdout/stderr, this script queries the service endpoints
that return cache statistics.
"""
import httpx
import sys
from datetime import datetime, timedelta

RECOMMENDER_SERVICE_URL = "http://localhost:3002"

def main():
    print("=" * 60)
    print("CACHE STATISTICS CHECKER")
    print("=" * 60)
    print()
    
    print("⚠️  NOTA: Los servicios actualmente no persisten estadísticas")
    print("   de cache en una base de datos. Los cache misses se reportan")
    print("   en tiempo real en las respuestas de los endpoints.")
    print()
    print("Para obtener estadísticas históricas, necesitarías:")
    print("  1. Implementar un sistema de logging persistente")
    print("  2. Agregar un endpoint de métricas en el servicio")
    print("  3. Usar una herramienta de monitoreo (Prometheus, etc.)")
    print()
    print("-" * 60)
    print()
    
    # Check if service is running
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{RECOMMENDER_SERVICE_URL}/health")
            if resp.status_code == 200:
                print("✓ Recommender Service está corriendo")
            else:
                print("✗ Recommender Service no responde correctamente")
                sys.exit(1)
    except Exception as e:
        print(f"✗ No se puede conectar al Recommender Service: {e}")
        print(f"  Asegúrate de que el servicio esté corriendo en {RECOMMENDER_SERVICE_URL}")
        sys.exit(1)
    
    print()
    print("SOLUCIÓN PROPUESTA:")
    print("-" * 60)
    print()
    print("Para monitorear cache misses en tiempo real, puedes:")
    print()
    print("1. Revisar los logs de stdout/stderr del proceso:")
    print("   $ ps aux | grep 'uvicorn services.recommender'")
    print("   $ tail -f /path/to/log/file  # si rediriges stdout a un archivo")
    print()
    print("2. Agregar un endpoint de métricas al servicio (recomendado):")
    print("   - Guardar estadísticas en una tabla de la DB")
    print("   - Exponer un endpoint /metrics o /stats")
    print()
    print("3. Usar el script de monitoreo en tiempo real:")
    print("   - Ejecutar recomendaciones y ver las stats en la respuesta")
    print()
    print("=" * 60)

if __name__ == "__main__":
    main()
