#!/bin/bash

# 🚀 Script Rápido: Subir a GitHub
# Ejecuta este script para subir tu código a GitHub en 2 minutos

echo "🚀 Subiendo Vinylbe a GitHub..."
echo ""

# Colores
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Paso 1: Verificar que .env no se suba
echo -e "${BLUE}Paso 1/5:${NC} Verificando que .env está protegido..."
if grep -q "^\.env$" .gitignore; then
    echo -e "${GREEN}✓${NC} .env está en .gitignore"
else
    echo ".env" >> .gitignore
    echo -e "${YELLOW}⚠${NC} Añadido .env a .gitignore"
fi

# Paso 2: Añadir todos los archivos
echo ""
echo -e "${BLUE}Paso 2/5:${NC} Añadiendo archivos al commit..."
git add .

# Verificar que .env no está staged
if git diff --cached --name-only | grep -q "^\.env$"; then
    echo -e "${RED}✗${NC} ERROR: .env está en el commit. Removiendo..."
    git reset .env
    echo -e "${GREEN}✓${NC} .env removido del commit"
fi

echo -e "${GREEN}✓${NC} Archivos añadidos"

# Paso 3: Hacer commit
echo ""
echo -e "${BLUE}Paso 3/5:${NC} Haciendo commit..."
git commit -m "Add deployment configuration and documentation

- Add Railway, Render, Fly.io, Docker configs
- Add deployment guides (GUIA_DESPLIEGUE.md, INICIO_RAPIDO.md)
- Add verification scripts (check_deploy.sh, prepare_deploy.sh)
- Update requirements.txt with all dependencies
- Add README.md with complete documentation
- Migrate to SQLite and remove Spotify integration"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Commit realizado"
else
    echo -e "${YELLOW}⚠${NC} No hay cambios nuevos para commit (puede que ya estén commiteados)"
fi

# Paso 4: Configurar remote de GitHub
echo ""
echo -e "${BLUE}Paso 4/5:${NC} Configurando GitHub..."
echo ""
echo "Necesitas crear un repositorio en GitHub primero:"
echo "1. Ve a https://github.com/new"
echo "2. Nombre: vinylbe"
echo "3. NO marques 'Add README' ni '.gitignore'"
echo "4. Click 'Create repository'"
echo "5. Copia la URL (https://github.com/TU_USUARIO/vinylbe.git)"
echo ""
read -p "Pega la URL de tu repositorio aquí: " repo_url

if [ -z "$repo_url" ]; then
    echo -e "${RED}✗${NC} No se proporcionó URL. Saliendo..."
    exit 1
fi

# Verificar si ya existe el remote 'origin'
if git remote | grep -q "^origin$"; then
    echo -e "${YELLOW}⚠${NC} Remote 'origin' ya existe. Actualizando URL..."
    git remote set-url origin "$repo_url"
else
    git remote add origin "$repo_url"
fi

echo -e "${GREEN}✓${NC} Remote configurado: $repo_url"

# Paso 5: Push a GitHub
echo ""
echo -e "${BLUE}Paso 5/5:${NC} Subiendo a GitHub..."
git branch -M main
git push -u origin main

if [ $? -eq 0 ]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${GREEN}✓ ¡Código subido a GitHub exitosamente!${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "🎉 Tu repositorio: $repo_url"
    echo ""
    echo "🚀 Próximos pasos:"
    echo "1. Ve a https://railway.app"
    echo "2. Login with GitHub"
    echo "3. 'Deploy from GitHub repo'"
    echo "4. Selecciona 'vinylbe'"
    echo "5. Configura variables de entorno"
    echo "6. ¡Despliega!"
    echo ""
    echo "📖 Guía completa: INICIO_RAPIDO.md"
    echo ""
else
    echo ""
    echo -e "${RED}✗ Error al hacer push${NC}"
    echo ""
    echo "Posibles soluciones:"
    echo "1. Si pide contraseña, usa un Personal Access Token:"
    echo "   - Ve a GitHub → Settings → Developer settings → Personal access tokens"
    echo "   - Generate new token (classic)"
    echo "   - Marca 'repo' scope"
    echo "   - Usa el token como contraseña"
    echo ""
    echo "2. Si dice 'repository not found':"
    echo "   - Verifica que creaste el repositorio en GitHub"
    echo "   - Verifica que la URL sea correcta"
    echo ""
    echo "3. Si dice 'permission denied':"
    echo "   - Verifica que estás autenticado en GitHub"
    echo "   - Usa SSH en lugar de HTTPS: git@github.com:TU_USUARIO/vinylbe.git"
    echo ""
fi
