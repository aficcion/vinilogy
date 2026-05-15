#!/bin/bash
# Script para reiniciar los servicios de Vinylbe

echo "🛑 Deteniendo servicios actuales..."
pkill -f "python3 start_services.py"
pkill -f "uvicorn"
sleep 2

echo "🚀 Iniciando servicios..."
cd /Users/carlosbautista/Downloads/Vinylbe
python3 start_services.py
