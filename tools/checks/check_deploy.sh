#!/bin/bash

# 🔍 Script de Verificación Pre-Despliegue
# Ejecuta este script antes de desplegar para asegurarte de que todo está listo

echo "🔍 Verificando configuración de Vinylbe para despliegue..."
echo ""

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

# Función para verificar
check() {
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} $1"
    else
        echo -e "${RED}✗${NC} $1"
        ((ERRORS++))
    fi
}

warn() {
    echo -e "${YELLOW}⚠${NC} $1"
    ((WARNINGS++))
}

# 1. Verificar que existe .gitignore
echo "📁 Verificando archivos de configuración..."
if [ -f ".gitignore" ]; then
    check ".gitignore existe"
    
    # Verificar que .env está en .gitignore
    if grep -q "^\.env$" .gitignore; then
        check ".env está en .gitignore"
    else
        warn ".env NO está en .gitignore - ¡Añádelo antes de hacer commit!"
        echo "  Ejecuta: echo '.env' >> .gitignore"
    fi
else
    warn ".gitignore no existe"
fi

# 2. Verificar archivos de despliegue
echo ""
echo "🚀 Verificando archivos de despliegue..."

[ -f "Procfile" ] && check "Procfile existe" || warn "Procfile no existe"
[ -f "requirements.txt" ] && check "requirements.txt existe" || warn "requirements.txt no existe"
[ -f "Dockerfile" ] && check "Dockerfile existe" || warn "Dockerfile no existe"
[ -f "railway.toml" ] && check "railway.toml existe" || warn "railway.toml no existe (opcional)"
[ -f "render.yaml" ] && check "render.yaml existe" || warn "render.yaml no existe (opcional)"

# 3. Verificar estructura de servicios
echo ""
echo "🏗️  Verificando estructura de servicios..."

[ -d "services/discogs" ] && check "Servicio Discogs existe" || warn "Servicio Discogs no encontrado"
[ -d "services/recommender" ] && check "Servicio Recommender existe" || warn "Servicio Recommender no encontrado"
[ -d "services/pricing" ] && check "Servicio Pricing existe" || warn "Servicio Pricing no encontrado"
[ -d "services/lastfm" ] && check "Servicio Last.fm existe" || warn "Servicio Last.fm no encontrado"
[ -d "gateway" ] && check "Gateway existe" || warn "Gateway no encontrado"

# 4. Verificar archivos principales de servicios
echo ""
echo "📦 Verificando archivos principales..."

[ -f "gateway/main.py" ] && check "gateway/main.py existe" || warn "gateway/main.py no encontrado"
[ -f "start_services.py" ] && check "start_services.py existe" || warn "start_services.py no encontrado"

# 5. Verificar variables de entorno
echo ""
echo "🔐 Verificando variables de entorno..."

if [ -f ".env" ]; then
    check ".env existe"
    
    # Verificar que contiene las claves necesarias
    grep -q "DISCOGS_API_KEY" .env && check "DISCOGS_API_KEY configurada" || warn "DISCOGS_API_KEY faltante"
    grep -q "LASTFM_API_KEY" .env && check "LASTFM_API_KEY configurada" || warn "LASTFM_API_KEY faltante"
    grep -q "EBAY_APP_ID" .env && check "EBAY_APP_ID configurada" || warn "EBAY_APP_ID faltante"
else
    warn ".env no existe - créalo desde .env.example"
fi

# 6. Verificar que .env.example existe (para documentación)
if [ -f ".env.example" ]; then
    check ".env.example existe (buena práctica)"
else
    warn ".env.example no existe - considera crearlo para documentar las variables necesarias"
fi

# 7. Verificar Python y dependencias
echo ""
echo "🐍 Verificando entorno Python..."

if command -v python3 &> /dev/null; then
    check "Python 3 instalado"
    PYTHON_VERSION=$(python3 --version)
    echo "  Versión: $PYTHON_VERSION"
else
    warn "Python 3 no encontrado"
fi

# 8. Verificar que requirements.txt tiene contenido
if [ -f "requirements.txt" ]; then
    LINES=$(wc -l < requirements.txt)
    if [ $LINES -gt 5 ]; then
        check "requirements.txt tiene dependencias ($LINES líneas)"
    else
        warn "requirements.txt parece incompleto (solo $LINES líneas)"
    fi
fi

# 9. Verificar base de datos
echo ""
echo "💾 Verificando base de datos..."

if [ -f "vinylbe.db" ]; then
    check "vinylbe.db existe"
    SIZE=$(du -h vinylbe.db | cut -f1)
    echo "  Tamaño: $SIZE"
else
    warn "vinylbe.db no existe - se creará en el primer arranque"
fi

# 10. Verificar Git
echo ""
echo "📚 Verificando Git..."

if [ -d ".git" ]; then
    check "Repositorio Git inicializado"
    
    # Verificar si hay cambios sin commit
    if git diff-index --quiet HEAD --; then
        check "No hay cambios sin commit"
    else
        warn "Hay cambios sin commit - considera hacer commit antes de desplegar"
    fi
    
    # Verificar remote
    if git remote -v | grep -q "origin"; then
        check "Remote 'origin' configurado"
        REMOTE=$(git remote get-url origin)
        echo "  Remote: $REMOTE"
    else
        warn "No hay remote configurado - necesitarás uno para desplegar"
    fi
else
    warn "No es un repositorio Git - inicializa con 'git init'"
fi

# 11. Test rápido de sintaxis Python
echo ""
echo "🧪 Verificando sintaxis Python..."

if command -v python3 &> /dev/null; then
    python3 -m py_compile start_services.py 2>/dev/null && check "start_services.py sintaxis OK" || warn "start_services.py tiene errores de sintaxis"
    python3 -m py_compile gateway/main.py 2>/dev/null && check "gateway/main.py sintaxis OK" || warn "gateway/main.py tiene errores de sintaxis"
fi

# Resumen final
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✓ ¡Todo listo para desplegar!${NC}"
    echo ""
    echo "Próximos pasos:"
    echo "1. Commit y push a GitHub: git add . && git commit -m 'Ready for deployment' && git push"
    echo "2. Sigue la guía en INICIO_RAPIDO.md"
    echo "3. Despliega en Railway, Render o tu plataforma preferida"
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠ Hay $WARNINGS advertencias pero puedes continuar${NC}"
    echo ""
    echo "Revisa las advertencias arriba y corrígelas si es necesario."
else
    echo -e "${RED}✗ Hay $ERRORS errores que debes corregir antes de desplegar${NC}"
    echo ""
    echo "Revisa los errores arriba y corrígelos antes de continuar."
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Exit code
if [ $ERRORS -eq 0 ]; then
    exit 0
else
    exit 1
fi
