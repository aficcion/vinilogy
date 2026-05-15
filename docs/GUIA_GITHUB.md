# 📤 Guía: Subir Vinylbe a GitHub

## Paso 1: Crear Repositorio en GitHub (2 minutos)

### 1.1 Ve a GitHub
1. Abre tu navegador
2. Ve a [github.com](https://github.com)
3. Si no tienes cuenta, créala (gratis, con email o Google)

### 1.2 Crear Nuevo Repositorio
1. Click en el **+** (arriba a la derecha)
2. Selecciona **"New repository"**
3. Rellena:
   - **Repository name**: `vinylbe`
   - **Description**: `Vinyl recommendation platform with Last.fm, Discogs and eBay`
   - **Visibility**: 
     - ✅ **Public** (si quieres que sea visible)
     - ✅ **Private** (si quieres que sea privado)
   - ⚠️ **NO marques** "Add a README file"
   - ⚠️ **NO marques** "Add .gitignore"
   - ⚠️ **NO marques** "Choose a license"
4. Click en **"Create repository"**

### 1.3 Copiar la URL
GitHub te mostrará una página con comandos. **Copia la URL** que aparece, será algo como:
```
https://github.com/TU_USUARIO/vinylbe.git
```

---

## Paso 2: Conectar tu Proyecto Local con GitHub (3 minutos)

### 2.1 Abrir Terminal
```bash
cd /Users/carlosbautista/Downloads/Vinylbe
```

### 2.2 Verificar Git
```bash
# Verificar que Git está inicializado
git status
```

Si dice "not a git repository", inicializa:
```bash
git init
```

### 2.3 Añadir Archivos
```bash
# Añadir todos los archivos (excepto los que están en .gitignore)
git add .

# Verificar qué se va a subir
git status
```

**⚠️ IMPORTANTE**: Verifica que `.env` NO aparece en la lista (debe estar ignorado)

### 2.4 Hacer Commit
```bash
git commit -m "Initial commit: Vinylbe vinyl recommendation platform"
```

### 2.5 Conectar con GitHub
```bash
# Reemplaza TU_USUARIO con tu usuario de GitHub
git remote add origin https://github.com/TU_USUARIO/vinylbe.git

# Renombrar rama a 'main' (si es necesario)
git branch -M main
```

### 2.6 Subir a GitHub
```bash
git push -u origin main
```

**Si te pide usuario y contraseña:**
- Usuario: tu usuario de GitHub
- Contraseña: **NO uses tu contraseña**, usa un **Personal Access Token**

---

## Paso 3: Crear Personal Access Token (si es necesario)

Si Git te pide contraseña y falla:

1. Ve a GitHub → **Settings** (tu perfil)
2. Scroll hasta **Developer settings** (abajo a la izquierda)
3. Click en **Personal access tokens** → **Tokens (classic)**
4. Click en **Generate new token** → **Generate new token (classic)**
5. Rellena:
   - **Note**: `Vinylbe deployment`
   - **Expiration**: `90 days` (o lo que prefieras)
   - **Scopes**: Marca ✅ **repo** (todos los permisos de repo)
6. Click en **Generate token**
7. **⚠️ COPIA EL TOKEN** (solo se muestra una vez)
8. Usa este token como contraseña cuando Git te lo pida

---

## Paso 4: Verificar que Funcionó

### 4.1 Verificar en GitHub
1. Ve a `https://github.com/TU_USUARIO/vinylbe`
2. Deberías ver todos tus archivos

### 4.2 Verificar localmente
```bash
git remote -v
```

Debería mostrar:
```
origin  https://github.com/TU_USUARIO/vinylbe.git (fetch)
origin  https://github.com/TU_USUARIO/vinylbe.git (push)
```

---

## ✅ ¡Listo! Ahora Puedes Desplegar

Una vez que tu código está en GitHub, puedes:

### Railway
1. Ve a [railway.app](https://railway.app)
2. Login with GitHub
3. "Deploy from GitHub repo"
4. Selecciona `vinylbe`

### Render
1. Ve a [render.com](https://render.com)
2. Sign up with GitHub
3. "New Web Service"
4. Conecta tu repo `vinylbe`

---

## 🆘 Problemas Comunes

### Error: "Permission denied"
**Solución**: Usa Personal Access Token en lugar de contraseña

### Error: "Repository not found"
**Solución**: Verifica que la URL sea correcta y que el repo exista

### Error: ".env appears in commit"
**Solución**: 
```bash
# Eliminar .env del staging
git rm --cached .env

# Asegurar que está en .gitignore
echo ".env" >> .gitignore

# Commit de nuevo
git add .gitignore
git commit -m "Remove .env from tracking"
git push
```

### Error: "Updates were rejected"
**Solución**:
```bash
# Si el repo en GitHub tiene archivos que no tienes local
git pull origin main --allow-unrelated-histories
git push origin main
```

---

## 📚 Próximos Pasos

Una vez que tu código está en GitHub:
1. ✅ Sigue la guía `INICIO_RAPIDO.md` para Railway
2. ✅ O usa `render.yaml` para Render
3. ✅ O cualquier otra opción de `GUIA_DESPLIEGUE.md`

---

## 💡 Comandos de Referencia Rápida

```bash
# Estado actual
git status

# Ver commits
git log --oneline

# Ver remote
git remote -v

# Actualizar después de cambios
git add .
git commit -m "Update: descripción del cambio"
git push origin main
```

---

¡Ahora tu código está en GitHub y listo para desplegar! 🚀
