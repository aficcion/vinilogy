#!/bin/bash

# Script para actualizar la base de datos de producción en Railway
# Este script sube la base de datos local a Railway

echo "🚀 Actualizando base de datos de producción en Railway..."

# Verificar que existe vinylbe.db
if [ ! -f "vinylbe.db" ]; then
    echo "❌ Error: vinylbe.db no encontrado"
    exit 1
fi

# Obtener la URL del servicio de Railway
RAILWAY_URL=$(railway variables get RAILWAY_PUBLIC_DOMAIN 2>/dev/null || echo "")

if [ -z "$RAILWAY_URL" ]; then
    echo "⚠️  No se pudo obtener la URL de Railway automáticamente"
    echo "Por favor, ingresa la URL de tu aplicación en Railway (sin https://):"
    read RAILWAY_URL
fi

# Asegurarse de que la URL tiene el formato correcto
RAILWAY_URL="https://${RAILWAY_URL#https://}"

echo "📡 Conectando a: $RAILWAY_URL"

# Crear un backup de la base de datos actual en Railway (opcional)
echo "📦 Descargando backup de la base de datos actual..."
curl -f "$RAILWAY_URL/api/admin/db/download" -o "vinylbe.db.railway.backup.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || echo "⚠️  No se pudo descargar backup (puede que no exista)"

# Subir la nueva base de datos
echo "⬆️  Subiendo nueva base de datos..."
RESPONSE=$(curl -X POST "$RAILWAY_URL/api/admin/db/upload" \
    -F "database=@vinylbe.db" \
    -w "\n%{http_code}" \
    -s)

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Base de datos actualizada exitosamente!"
    echo "$BODY"
else
    echo "❌ Error al actualizar la base de datos (HTTP $HTTP_CODE)"
    echo "$BODY"
    exit 1
fi

echo ""
echo "🎉 Proceso completado!"
echo "La base de datos de producción ha sido sobrescrita con tu base de datos local."
