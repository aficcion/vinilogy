#!/bin/bash
# Script de restauración rápida al punto v1.0.0-prod-ready

set -e

echo "🔄 Restaurando Vinylbe a v1.0.0-prod-ready..."
echo ""

# Verificar que estamos en el directorio correcto
if [ ! -f "vinylbe.db" ]; then
    echo "❌ Error: No se encuentra vinylbe.db. ¿Estás en el directorio correcto?"
    exit 1
fi

# Crear backup del estado actual
echo "📦 Creando backup del estado actual..."
BACKUP_DIR="recovery_points/before_restore_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp vinylbe.db "$BACKUP_DIR/vinylbe.db"
git log -1 --oneline > "$BACKUP_DIR/git_state.txt"
echo "✅ Backup guardado en: $BACKUP_DIR"
echo ""

# Restaurar código
echo "📝 Restaurando código a v1.0.0-prod-ready..."
git checkout v1.0.0-prod-ready
echo "✅ Código restaurado"
echo ""

# Restaurar base de datos
echo "💾 Restaurando base de datos..."
if [ -f "recovery_points/vinylbe_20251203_090358.db" ]; then
    cp recovery_points/vinylbe_20251203_090358.db vinylbe.db
    echo "✅ Base de datos restaurada"
else
    echo "❌ Error: No se encuentra el backup de la base de datos"
    exit 1
fi
echo ""

# Verificar restauración
echo "🔍 Verificando restauración..."
USERS=$(sqlite3 vinylbe.db "SELECT COUNT(*) FROM user;")
ARTISTS=$(sqlite3 vinylbe.db "SELECT COUNT(*) FROM artists;")
ALBUMS=$(sqlite3 vinylbe.db "SELECT COUNT(*) FROM albums;")

echo "   Usuarios: $USERS (esperado: 0)"
echo "   Artistas: $ARTISTS (esperado: 381)"
echo "   Álbumes: $ALBUMS (esperado: 2801)"
echo ""

if [ "$USERS" -eq 0 ] && [ "$ARTISTS" -eq 381 ] && [ "$ALBUMS" -eq 2801 ]; then
    echo "✅ Restauración completada exitosamente!"
    echo ""
    echo "📋 Próximos pasos:"
    echo "   1. Iniciar servicios: python start_services.py"
    echo "   2. Verificar health: curl http://localhost:5000/health"
    echo "   3. Si todo funciona, hacer push: git push origin main --force"
else
    echo "⚠️  Advertencia: Los números no coinciden con lo esperado"
    echo "   Revisa manualmente antes de continuar"
fi
echo ""
echo "💡 Para volver a main: git checkout main"
