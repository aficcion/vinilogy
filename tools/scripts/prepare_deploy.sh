#!/bin/bash

# 🚀 Script de Despliegue Rápido
# Este script automatiza los pasos básicos para preparar el despliegue

echo "🚀 Preparando Vinylbe para despliegue..."
echo ""

# Colores
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 1. Verificar estado
echo -e "${BLUE}Paso 1/4:${NC} Verificando configuración..."
./check_deploy.sh
if [ $? -ne 0 ]; then
    echo ""
    echo -e "${YELLOW}⚠ Hay problemas que debes revisar antes de continuar${NC}"
    read -p "¿Deseas continuar de todos modos? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 2. Git status
echo ""
echo -e "${BLUE}Paso 2/4:${NC} Verificando Git..."

if [ ! -d ".git" ]; then
    echo "Inicializando repositorio Git..."
    git init
    echo -e "${GREEN}✓${NC} Git inicializado"
fi

# Verificar si hay cambios
if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    echo "Hay cambios sin commit. Archivos modificados:"
    git status --short
    echo ""
    read -p "¿Hacer commit de estos cambios? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git add .
        read -p "Mensaje de commit (Enter para usar 'Prepare for deployment'): " commit_msg
        commit_msg=${commit_msg:-"Prepare for deployment"}
        git commit -m "$commit_msg"
        echo -e "${GREEN}✓${NC} Commit realizado"
    fi
else
    echo -e "${GREEN}✓${NC} No hay cambios sin commit"
fi

# 3. Verificar remote
echo ""
echo -e "${BLUE}Paso 3/4:${NC} Verificando remote de GitHub..."

if ! git remote | grep -q "origin"; then
    echo "No hay remote configurado."
    echo ""
    echo "Opciones:"
    echo "1. Tengo un repositorio en GitHub (introduce la URL)"
    echo "2. Necesito crear un repositorio nuevo"
    echo "3. Saltar este paso (configurar después)"
    echo ""
    read -p "Selecciona una opción (1/2/3): " -n 1 -r
    echo
    
    case $REPLY in
        1)
            read -p "URL del repositorio (https://github.com/usuario/repo.git): " repo_url
            git remote add origin "$repo_url"
            echo -e "${GREEN}✓${NC} Remote configurado: $repo_url"
            ;;
        2)
            echo ""
            echo "Pasos para crear un repositorio en GitHub:"
            echo "1. Ve a https://github.com/new"
            echo "2. Nombre: vinylbe"
            echo "3. Descripción: Vinyl recommendation app"
            echo "4. Público o Privado (tu elección)"
            echo "5. NO inicialices con README, .gitignore o licencia"
            echo "6. Copia la URL del repositorio"
            echo ""
            read -p "Pega la URL aquí: " repo_url
            git remote add origin "$repo_url"
            echo -e "${GREEN}✓${NC} Remote configurado: $repo_url"
            ;;
        3)
            echo -e "${YELLOW}⚠${NC} Remote no configurado - deberás hacerlo manualmente"
            ;;
    esac
else
    REMOTE=$(git remote get-url origin)
    echo -e "${GREEN}✓${NC} Remote ya configurado: $REMOTE"
fi

# 4. Push (opcional)
echo ""
echo -e "${BLUE}Paso 4/4:${NC} Push a GitHub..."

if git remote | grep -q "origin"; then
    read -p "¿Hacer push a GitHub ahora? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Verificar si la rama existe en remote
        if git ls-remote --exit-code --heads origin main &>/dev/null; then
            git push origin main
        else
            # Primera vez, crear rama main
            git branch -M main
            git push -u origin main
        fi
        
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓${NC} Push exitoso"
        else
            echo -e "${YELLOW}⚠${NC} Push falló - verifica tus credenciales"
        fi
    fi
else
    echo -e "${YELLOW}⚠${NC} No hay remote configurado - saltando push"
fi

# Resumen final
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✓ Preparación completada${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🎯 Próximos pasos:"
echo ""
echo "1. Ve a https://railway.app"
echo "2. Click en 'Start a New Project'"
echo "3. Selecciona 'Deploy from GitHub repo'"
echo "4. Selecciona tu repositorio 'vinylbe'"
echo "5. Configura las variables de entorno:"
echo "   - DISCOGS_API_KEY"
echo "   - DISCOGS_API_SECRET"
echo "   - LASTFM_API_KEY"
echo "   - LASTFM_API_SECRET"
echo "   - EBAY_APP_ID"
echo "   - EBAY_CERT_ID"
echo "6. ¡Despliega!"
echo ""
echo "📖 Guía detallada: INICIO_RAPIDO.md"
echo ""

if git remote | grep -q "origin"; then
    REMOTE=$(git remote get-url origin)
    echo "🔗 Tu repositorio: $REMOTE"
    echo ""
fi

echo "¡Buena suerte! 🚀"
