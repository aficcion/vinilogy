# Google Custom Search API - Configuración para FNAC

## Paso 1: Crear Proyecto en Google Cloud

1. Ve a [Google Cloud Console](https://console.cloud.google.com/)
2. Crea un nuevo proyecto o selecciona uno existente
3. Nombre sugerido: "Vinylbe FNAC Scraper"

## Paso 2: Habilitar Custom Search API

1. En el menú lateral, ve a **APIs & Services** → **Library**
2. Busca "Custom Search API"
3. Haz clic en **Enable**

## Paso 3: Crear API Key

1. Ve a **APIs & Services** → **Credentials**
2. Haz clic en **Create Credentials** → **API Key**
3. Copia la API key generada
4. (Opcional) Haz clic en **Restrict Key** para mayor seguridad:
   - **Application restrictions**: None (o IP addresses si quieres restringir)
   - **API restrictions**: Restrict key → Selecciona "Custom Search API"

## Paso 4: Crear Custom Search Engine

1. Ve a [Google Programmable Search Engine](https://programmablesearchengine.google.com/)
2. Haz clic en **Add** o **Create**
3. Configuración:
   - **Sites to search**: `www.fnac.es`
   - **Name**: "FNAC Vinyl Search"
   - **Language**: Spanish
4. Haz clic en **Create**
5. En la página de configuración:
   - Ve a **Setup** → **Basics**
   - Copia el **Search engine ID** (cx)
   - En **Search features**, activa **Search the entire web**

## Paso 5: Configurar Variables de Entorno

Añade a tu archivo `.env`:

```bash
# Google Custom Search API
GOOGLE_CUSTOM_SEARCH_API_KEY=tu_api_key_aqui
GOOGLE_CUSTOM_SEARCH_ENGINE_ID=tu_search_engine_id_aqui
```

## Paso 6: Instalar Dependencia

```bash
pip install google-api-python-client
```

O añade a `requirements.txt`:
```
google-api-python-client==2.108.0
```

## Límites y Costos

### Gratis
- **100 búsquedas por día** - GRATIS
- Perfecto para empezar y probar

### De Pago
- Después de 100 búsquedas/día: **$5 por 1,000 búsquedas**
- Máximo: 10,000 búsquedas/día

### Estimación para Vinylbe
- Si tienes ~50 búsquedas de FNAC por día → **GRATIS**
- Si tienes ~500 búsquedas por día → ~$10/mes
- Si tienes ~1000 búsquedas por día → ~$22.50/mes

## Verificación

Prueba tu configuración con:

```bash
python3 test_google_search.py
```

## Troubleshooting

### Error: "API key not valid"
- Verifica que la API key esté correcta
- Asegúrate de haber habilitado Custom Search API

### Error: "Daily Limit Exceeded"
- Has superado las 100 búsquedas gratuitas del día
- Espera hasta mañana o habilita facturación

### No encuentra resultados
- Verifica que el Search Engine ID sea correcto
- Asegúrate de haber activado "Search the entire web"
