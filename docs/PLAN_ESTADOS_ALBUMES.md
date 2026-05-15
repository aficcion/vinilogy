# Plan de Corrección: Sistema de Estados de Álbumes

## 📊 Estado Actual del Sistema

### Arquitectura de Datos

#### Base de Datos (SQLite)
- **Tabla**: `recommendation`
- **Campo de estado**: `status`
- **Valores permitidos**: `'neutral'`, `'favorite'`, `'disliked'`, `'owned'`
- **Valor por defecto**: `'neutral'` (cuando se crea una recomendación)

#### Frontend (JavaScript)
- **Almacenamiento**: `Map` llamado `albumStatuses`
- **Clave**: `"artist|album"` (string concatenado)
- **Valores**: `'favorite'`, `'owned'`, `'disliked'`, o `null` (sin estado especial)

### Flujo Actual (CON PROBLEMAS)

```
1. Usuario carga la app
   ↓
2. Frontend llama: GET /api/users/{userId}/recommendations
   ↓
3. Backend ejecuta: get_recommendations_for_user()
   ↓
   ❌ PROBLEMA 1: Solo devuelve status IN ('neutral', 'favorite')
   ↓
4. Frontend recibe recomendaciones (SIN owned ni disliked)
   ↓
5. Frontend ejecuta: syncAlbumStatusesFromRecs()
   ↓
   ❌ PROBLEMA 2: Filtra rec.status !== 'pending' (pero 'pending' no existe en DB)
   ↓
6. Usuario marca álbum como "Ya lo tengo" (owned)
   ↓
7. Frontend actualiza: albumStatuses.set(key, 'owned')
   ↓
8. Frontend llama: PATCH /users/{userId}/recommendations/{recId}
   ↓
   ❌ PROBLEMA 3: Envía { new_status: 'pending' } cuando status es null
   ↓
9. Backend actualiza DB con status = 'owned'
   ↓
10. Frontend ejecuta: filterRecommendations('all')
    ↓
    ✅ Álbum desaparece de "Todas" (correcto)
    ↓
11. Usuario va a "Colección"
    ↓
    ❌ PROBLEMA 4: albumStatuses tiene 'owned', pero allRecommendations NO
    ↓
    ❌ RESULTADO: Vista vacía
    ↓
12. Usuario recarga página (F5)
    ↓
13. Backend NO devuelve álbumes con status 'owned'
    ↓
    ❌ RESULTADO: Se pierden los estados
```

---

## 🎯 Estado Deseado del Sistema

### Principios de Diseño

1. **Single Source of Truth**: La base de datos es la única fuente de verdad
2. **Frontend como Vista**: El frontend solo muestra lo que hay en DB
3. **Sincronización Inmediata**: Cada cambio se guarda en DB inmediatamente
4. **Persistencia Completa**: Los estados sobreviven a recargas y re-login

### Flujo Deseado (CORRECTO)

```
1. Usuario carga la app
   ↓
2. Frontend llama: GET /api/users/{userId}/recommendations
   ↓
3. Backend ejecuta: get_recommendations_for_user()
   ↓
   ✅ CORRECCIÓN 1: Devuelve TODAS las recomendaciones (todos los status)
   ↓
4. Frontend recibe recomendaciones (CON owned, disliked, favorite, neutral)
   ↓
5. Frontend ejecuta: syncAlbumStatusesFromRecs()
   ↓
   ✅ CORRECCIÓN 2: Sincroniza TODOS los status
   ✅ Mapea 'neutral' → null (sin estado especial)
   ✅ Mapea 'favorite' → 'favorite'
   ✅ Mapea 'owned' → 'owned'
   ✅ Mapea 'disliked' → 'disliked'
   ↓
6. Frontend almacena en memoria:
   - allRecommendations = [...] (TODAS las recomendaciones)
   - albumStatuses = Map con todos los estados
   ↓
7. Usuario marca álbum como "Ya lo tengo" (owned)
   ↓
8. Frontend actualiza: albumStatuses.set(key, 'owned')
   ↓
9. Frontend llama: PATCH /users/{userId}/recommendations/{recId}
   ↓
   ✅ CORRECCIÓN 3: Envía { new_status: 'owned' }
   ↓
10. Backend actualiza DB: status = 'owned'
    ↓
11. Frontend ejecuta: filterRecommendations('all')
    ↓
    ✅ Filtra allRecommendations excluyendo owned y disliked
    ↓
    ✅ Álbum desaparece de "Todas" (correcto)
    ↓
12. Usuario va a "Colección"
    ↓
    ✅ Filtra allRecommendations donde status === 'owned'
    ↓
    ✅ RESULTADO: Álbum aparece en "Colección"
    ↓
13. Usuario recarga página (F5)
    ↓
14. Backend devuelve TODAS las recomendaciones (incluyendo owned)
    ↓
15. Frontend sincroniza estados desde DB
    ↓
    ✅ RESULTADO: Estados persisten correctamente
```

---

## 🔧 Cambios Necesarios

### 1. Backend: `gateway/db.py`

**Archivo**: `/Users/carlosbautista/Downloads/Vinylbe/gateway/db.py`

**Función**: `get_recommendations_for_user()` (líneas ~402-439)

**Cambio**:
```python
# ELIMINAR estas líneas:
if include_favorites:
    query += " AND r.status IN ('neutral', 'favorite')"
else:
    query += " AND r.status = 'neutral'"

# RESULTADO: La query devuelve TODAS las recomendaciones sin filtrar por status
```

**Justificación**: El filtrado debe hacerse en el frontend, no en el backend. El backend debe devolver todos los datos y dejar que el frontend decida qué mostrar según la vista activa.

---

### 2. Frontend: `gateway/static/app-user.js`

**Archivo**: `/Users/carlosbautista/Downloads/Vinylbe/gateway/static/app-user.js`

#### Cambio 2.1: `syncAlbumStatusesFromRecs()` (líneas ~316-326)

**Cambio**:
```javascript
function syncAlbumStatusesFromRecs(recommendations) {
    albumStatuses.clear();
    recommendations.forEach(rec => {
        const { artist, album } = getRecArtistAndAlbum(rec);
        if (rec.status) {
            const key = `${artist}|${album}`;
            // Mapear 'neutral' a null (sin estado especial en frontend)
            albumStatuses.set(key, rec.status === 'neutral' ? null : rec.status);
        }
    });
}
```

**Justificación**: 
- Sincronizar TODOS los estados desde la DB
- Mapear 'neutral' a `null` porque en el frontend `null` significa "sin estado especial"
- Esto asegura que `albumStatuses` refleje exactamente lo que hay en la DB

---

### 3. Frontend: `gateway/static/app-user-ext.js`

**Archivo**: `/Users/carlosbautista/Downloads/Vinylbe/gateway/static/app-user-ext.js`

#### Cambio 3.1: `setAlbumStatus()` (línea ~52)

**Cambio**:
```javascript
// ANTES:
body: JSON.stringify({ new_status: status || 'pending' })

// DESPUÉS:
body: JSON.stringify({ new_status: status || 'neutral' })
```

**Justificación**: 
- Cuando se desmarca un álbum (status = null), debe volver a 'neutral' en la DB
- 'pending' no existe en el esquema de la DB
- 'neutral' es el estado por defecto correcto

---

## 🧪 Casos de Prueba

### Caso 1: Marcar como "Ya lo tengo"
```
ACCIÓN: Click en botón "✓" de un álbum en vista "Todas"

ESPERADO:
1. Álbum desaparece de "Todas" con animación suave
2. Álbum aparece en vista "✓ Colección"
3. Estado se guarda en DB (status = 'owned')
4. Al recargar (F5), álbum sigue en "Colección" y NO en "Todas"
```

### Caso 2: Marcar como "No me interesa"
```
ACCIÓN: Click en botón "✗" de un álbum en vista "Todas"

ESPERADO:
1. Álbum desaparece de "Todas" con animación suave
2. Álbum aparece en vista "✗ Descartes"
3. Estado se guarda en DB (status = 'disliked')
4. Al recargar (F5), álbum sigue en "Descartes" y NO en "Todas"
```

### Caso 3: Marcar como "Favorito"
```
ACCIÓN: Click en botón "★" de un álbum en vista "Todas"

ESPERADO:
1. Álbum permanece en "Todas" (con estrella activa)
2. Álbum aparece en vista "★ Favoritos"
3. Estado se guarda en DB (status = 'favorite')
4. Al recargar (F5), álbum sigue en ambas vistas con estrella activa
```

### Caso 4: Desmarcar un estado
```
ACCIÓN: Click en botón activo (ej. "✓" ya marcado)

ESPERADO:
1. Botón se desmarca visualmente
2. Si estaba en vista filtrada (ej. "Colección"), álbum desaparece
3. Álbum vuelve a aparecer en "Todas"
4. Estado se guarda en DB (status = 'neutral')
5. Al recargar (F5), álbum está en "Todas" sin marcas
```

### Caso 5: Persistencia tras logout/login
```
ACCIÓN: 
1. Marcar varios álbumes con diferentes estados
2. Cerrar sesión
3. Volver a iniciar sesión

ESPERADO:
1. Todos los estados se mantienen
2. Álbumes aparecen en las vistas correctas
3. Botones muestran el estado correcto (activos/inactivos)
```

---

## 📋 Checklist de Implementación

### Fase 1: Correcciones Backend
- [ ] Modificar `get_recommendations_for_user()` en `gateway/db.py`
- [ ] Verificar que devuelve TODAS las recomendaciones
- [ ] Probar endpoint manualmente: `GET /api/users/1/recommendations`

### Fase 2: Correcciones Frontend - Sincronización
- [ ] Modificar `syncAlbumStatusesFromRecs()` en `app-user.js`
- [ ] Verificar que mapea correctamente todos los estados
- [ ] Añadir logs de debug para verificar sincronización

### Fase 3: Correcciones Frontend - Actualización
- [ ] Modificar `setAlbumStatus()` en `app-user-ext.js`
- [ ] Cambiar 'pending' → 'neutral'
- [ ] Verificar que PATCH envía el status correcto

### Fase 4: Pruebas
- [ ] Ejecutar Caso de Prueba 1 (Ya lo tengo)
- [ ] Ejecutar Caso de Prueba 2 (No me interesa)
- [ ] Ejecutar Caso de Prueba 3 (Favorito)
- [ ] Ejecutar Caso de Prueba 4 (Desmarcar)
- [ ] Ejecutar Caso de Prueba 5 (Persistencia)

### Fase 5: Verificación
- [ ] Inspeccionar DB directamente (SQLite browser)
- [ ] Verificar que los status se guardan correctamente
- [ ] Verificar que no hay estados 'pending' en la DB
- [ ] Verificar que las vistas filtradas funcionan correctamente

---

## 🚨 Riesgos y Mitigaciones

### Riesgo 1: Datos existentes con status incorrecto
**Problema**: Puede haber recomendaciones en DB con status = 'pending'

**Mitigación**: Ejecutar script de migración:
```sql
UPDATE recommendation SET status = 'neutral' WHERE status = 'pending';
```

### Riesgo 2: Rendimiento con muchas recomendaciones
**Problema**: Devolver TODAS las recomendaciones puede ser lento

**Mitigación**: 
- Añadir índice en columna `status` si no existe
- Limitar a 500 recomendaciones por usuario
- Implementar paginación si es necesario

### Riesgo 3: Inconsistencia durante la transición
**Problema**: Usuarios activos durante el despliegue pueden ver estados inconsistentes

**Mitigación**:
- Forzar recarga de página tras despliegue
- Limpiar localStorage al detectar versión antigua
- Mostrar mensaje "Actualizando..." durante sincronización inicial

---

## ✅ Criterios de Aceptación

El sistema estará CORRECTO cuando:

1. ✅ Un álbum marcado como "Ya lo tengo" desaparece de "Todas" y aparece en "Colección"
2. ✅ Un álbum marcado como "No me interesa" desaparece de "Todas" y aparece en "Descartes"
3. ✅ Un álbum marcado como "Favorito" permanece en "Todas" Y aparece en "Favoritos"
4. ✅ Al recargar la página (F5), todos los estados persisten correctamente
5. ✅ Al cerrar sesión y volver a entrar, todos los estados persisten correctamente
6. ✅ No hay álbumes "fantasma" (que desaparecen al navegar entre vistas)
7. ✅ La base de datos solo contiene status válidos: 'neutral', 'favorite', 'owned', 'disliked'
8. ✅ No hay errores en la consola del navegador
9. ✅ Las animaciones de desaparición funcionan suavemente
10. ✅ Los contadores de cada vista son correctos

---

## 📝 Notas Adicionales

### Alternativa: Filtrado en Backend
Si el rendimiento es un problema, podríamos:
1. Crear endpoints separados para cada vista:
   - `GET /api/users/{id}/recommendations/all` → neutral + favorite
   - `GET /api/users/{id}/recommendations/owned` → owned
   - `GET /api/users/{id}/recommendations/disliked` → disliked
   - `GET /api/users/{id}/recommendations/favorites` → favorite

2. Ventajas:
   - Menos datos transferidos
   - Queries más eficientes
   - Mejor para paginación

3. Desventajas:
   - Más complejidad en el backend
   - Más llamadas HTTP
   - Más difícil mantener sincronización

**Recomendación**: Empezar con la solución simple (devolver todo) y optimizar solo si hay problemas de rendimiento.

---

## 🎬 Próximos Pasos

1. **REVISAR** este plan con el usuario
2. **APROBAR** los cambios propuestos
3. **IMPLEMENTAR** las correcciones en orden
4. **PROBAR** cada caso de prueba
5. **VERIFICAR** criterios de aceptación
6. **DESPLEGAR** a producción

---

**Fecha**: 2025-11-27
**Autor**: Antigravity AI
**Estado**: Pendiente de Aprobación
