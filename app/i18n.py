"""i18n ligero para Vinilogy (ES por defecto + EN).

Sin frameworks ni build step: un diccionario `ES → EN` indexado por el propio texto
español (la "clave" es el string fuente), y un helper `t(texto, lang)`. Ventajas:
  · las plantillas quedan legibles: `{{ t('Precios en tiendas ES') }}`.
  · fallback natural: si falta una traducción, se muestra el español (nunca una clave
    cruda ni un hueco) → la web funciona aunque la traducción esté a medias.

Idioma por petición: cookie `vb_lang` (elección explícita del selector) > cabecera
Accept-Language (autodetección) > 'es'.
"""
from __future__ import annotations

SUPPORTED = ("es", "en")
DEFAULT = "es"
LANG_COOKIE = "vb_lang"

# ES → EN. Se rellena por bloques a medida que se traducen las plantillas/etiquetas.
# Clave = texto español EXACTO tal como aparece en la plantilla (sin espacios de más).
EN: dict[str, str] = {
    # ── cabecera / nav (base.html) ──
    "Busca un disco o un artista…": "Search a record or an artist…",
    "Buscar": "Search",
    "Por vibra ✦": "By vibe ✦",
    "Wishlist": "Wishlist",
    "Cuenta": "Account",
    "Salir": "Log out",
    "Entrar o crear cuenta": "Sign in or create account",
    "Cambiar tema": "Toggle theme",
    "Tu wishlist": "Your wishlist",
    # ── footer ──
    "Vinilogy · precios de vinilo en tiendas independientes de España":
        "Vinilogy · vinyl prices at independent record shops in Spain",
    "Privacidad": "Privacy",
    # ── home ──
    "Vinilogy — busca cualquier vinilo y su precio en tiendas de España":
        "Vinilogy — find any vinyl and its price at record shops in Spain",
    "No compras canciones. Compras discos.": "You don't buy songs. You buy records.",
    "Deja de rastrear tiendas.": "Stop hunting shops.",
    "Busca el disco y": "Find the record —",
    "punto": "done",
    "Vinilogy junta las ediciones en vinilo de cualquier álbum y lo que cuesta en":
        "Vinilogy gathers the vinyl editions of any album and what they cost at",
    "tiendas independientes de España": "independent record shops in Spain",
    "Tú solo eliges cuál cae este mes.": "You just pick which one to buy this month.",
    "¿No sabes qué buscar? Prueba la": "Not sure what to look for? Try the",
    "recomendación por vibra ✦": "vibe-based recommendation ✦",
    "Guarda discos con": "Save records with",
    "sin cuenta, o": "without an account, or",
    "entra con Google": "sign in with Google",
    "En tiendas ahora": "In shops now",
    "precios reales de tiendas independientes ES": "real prices from independent ES shops",
    "Hazla": "Make it",
    "tuya": "yours",
    "Conecta tus cuentas y deja de ser un catálogo para volverse tuyo":
        "Connect your accounts and turn a catalog into something that's yours",
    "Importa tu colección y calcula tu": "Import your collection and work out your",
    "gap de vinilo": "vinyl gap",
    ", con precios ES.": ", with ES prices.",
    "Afina la reco con lo que": "Tune the recs to what you",
    "de verdad escuchas": "actually listen to",
    "Conectar": "Connect",
    # ── search / artist / vibra ──
    "Tu selección": "Your selection",
    "Los discos que has elegido": "The records you've picked",
    "Mejores de": "Best of",
    "Sus mejores álbumes en vinilo": "Their best albums on vinyl",
    ", que aún no tienes": ", that you don't have yet",
    "En la onda de tu selección": "In the vibe of your selection",
    "Otros artistas afines a lo que has elegido, con vinilo.":
        "Other artists similar to what you've picked, on vinyl.",
    "No hemos encontrado afines para tu selección.":
        "We couldn't find any similar records for your selection.",
    "Tu selección no ha dado resultados con vinilo y portada.":
        "Your selection returned no results with vinyl and cover art.",
    "Escribe algo en el buscador para empezar.":
        "Type something in the search box to get started.",
    "Resultados para": "Results for",
    "Artistas": "Artists",
    "Obras con vinilo": "Records on vinyl",
    "No hemos encontrado obras con vinilo para":
        "We couldn't find any records on vinyl for",
    "Vinilos afines": "Similar vinyl",
    "a": "to",
    "Otros artistas en la misma onda, con vinilo.":
        "Other artists in the same vibe, on vinyl.",
    "Escuchar en Spotify": "Listen on Spotify",
    "Discografía en vinilo": "Discography on vinyl",
    "Ordenada por relevancia (lo más escuchado primero).":
        "Sorted by relevance (most listened first).",
    "Sin álbumes de estudio o EPs en vinilo localizados.":
        "No studio albums or EPs on vinyl found.",
    "En la onda de": "In the vibe of",
    "Otros artistas afines, con vinilo.": "Other similar artists, on vinyl.",
    "Sin afines localizados para este artista.":
        "No similar artists found for this artist.",
    "Recomendación por vibra": "Vibe-based recommendation",
    "Dime el ambiente y te saco vinilos que casen. Elige una vibra o descríbela con tus palabras.":
        "Tell me the mood and I'll pull vinyl that fits. Pick a vibe or describe it in your own words.",
    "algo para un domingo lluvioso…": "something for a rainy Sunday…",
    "Buscar vibra": "Search vibe",
    "Vinilos con vibra": "Vinyl with the vibe",
    "Ordenados por relevancia, con vinilo. Cada uno lleva su porqué.":
        "Sorted by relevance, on vinyl. Each one comes with its reason.",
    "No hemos localizado vinilos para esta vibra ahora mismo.":
        "We couldn't find any vinyl for this vibe right now.",
    "No reconozco esa vibra. Prueba con una de estas:":
        "I don't recognize that vibe. Try one of these:",
    # ── work.html + parciales (afines, cards) ──
    "Portada de": "Cover of",
    "Ya lo tienes en tu colección": "Already in your collection",
    "En tu colección": "In your collection",
    "Vinilo": "Vinyl",
    "Guardar en tu wishlist": "Save to your wishlist",
    "Guardar": "Save",
    "Escuchar en": "Listen on",
    "Ver en": "View on",
    "más sobre": "more about",
    "Precios en tiendas ES": "Prices at ES shops",
    "Algún dato de tienda puede estar desactualizado (más antiguo:":
        "Some shop data may be out of date (oldest:",
    "Precio": "Price",
    "Tienda": "Shop",
    "Disponibilidad": "Availability",
    "Ver en tienda": "View at shop",
    "El precio corresponde al": "The price is for the",
    "álbum": "album",
    ", no a un prensaje concreto (año, color, catálogo). Confirma la edición exacta en la tienda antes de comprar.":
        ", not a specific pressing (year, color, catalog). Confirm the exact edition at the shop before buying.",
    "Sin precio localizado en tiendas ES para esta obra.":
        "No price found at ES shops for this record.",
    "La crítica dice": "What the critics say",
    "Según la crítica suena a:": "According to the critics it sounds like:",
    "Temas destacados:": "Standout tracks:",
    "Reseñas en:": "Reviews at:",
    "Canciones": "Songs",
    "Tracklist de la edición de referencia del disco.":
        "Tracklist of the record's reference edition.",
    "Lo tienes": "You own it",
    "Álbum": "Album",
    "ver ficha": "view details",
    "desde": "from",
    "Afines por lo que dice la crítica": "Similar by what the critics say",
    "Otros vinilos con una vibra editorial cercana, según la prensa española.":
        "Other records with a close editorial vibe, according to the Spanish press.",
    "Otros artistas afines en género y estilo, con vinilo.":
        "Other similar artists in genre and style, on vinyl.",
    "Sin afines localizados para esta obra.": "No similar records found for this one.",
    "Afín": "Similar",
    "recomendación": "recommendation",
    "edición": "edition",
    "en vinilo": "on vinyl",
    "sin precio en tiendas ES": "no price at ES shops",
    # ── mi.html / cuenta.html ──
    "Tu Vinilogy personal": "Your personal Vinilogy",
    "Recomendaciones a tu medida y tu gap de vinilo. Necesitas una cuenta para verlas.":
        "Recommendations made for you and your vinyl gap. You need an account to see them.",
    "Entrar con Google": "Sign in with Google",
    "Conecta": "Connect",
    "para importar tu colección real (y tu": "to import your real collection (and your",
    ") o": ") or",
    "para afinar por tu escucha. Mientras, tu": "to fine-tune by what you listen to. Meanwhile, your",
    "ya funciona sin cuenta.": "already works without an account.",
    "Hola,": "Hi,",
    "ítems en tu colección": "items in your collection",
    "en CD": "on CD",
    "Aún no hemos importado tu colección.": "We haven't imported your collection yet.",
    "valor aprox.": "approx. value",
    "o": "or",
    "en": "in",
    "para": "to",
    "importar tu colección y afinar por tu escucha":
        "import your collection and fine-tune by what you listen to",
    "importar tu colección y ver tu gap de vinilo":
        "import your collection and see your vinyl gap",
    "afinar por tu escucha": "fine-tune by what you listen to",
    "Para ti": "For you",
    "En la onda de lo que ya tienes, con vinilo. Nada que ya poseas.":
        "In the vein of what you already have, on vinyl. Nothing you already own.",
    "Ver más": "Show more",
    "Necesitamos algo de tu colección (o escucha) para recomendarte a medida. Conecta Discogs/Last.fm en la próxima entrega.":
        "We need something from your collection (or listening) to recommend for you. Connect Discogs/Last.fm in the next release.",
    "Basado en lo que escuchas": "Based on what you listen to",
    "Discos que escuchas y aún no tienes": "Records you listen to and don't own yet",
    ", y": ", and",
    "Discos que escuchas para": "Records you listen to to",
    "subir de formato a vinilo": "upgrade to vinyl",
    ", más": ", plus",
    "Más": "More",
    "discos de los artistas que escuchas": "records by the artists you listen to",
    ". En vinilo, nada que ya tengas.": ". On vinyl, nothing you already have.",
    "Sube a vinilo": "Upgrade to vinyl",
    "Discos que tienes en otro formato y existen en vinilo (":
        "Records you have in another format that exist on vinyl (",
    "en total). Con sus ediciones y precio en tiendas ES.":
        "in total). With their editions and ES prices.",
    "No hemos localizado gap de vinilo en tu colección (o aún no está importada).":
        "We haven't found any vinyl gap in your collection (or it isn't imported yet).",
    "Entra o crea tu cuenta": "Sign in or create your account",
    "Una cuenta conserva tu wishlist en todos tus dispositivos y te da recomendaciones a tu medida. Entra con lo que ya uses: la primera vez crea tu cuenta, las siguientes te identifica. Sin contraseñas.":
        "An account keeps your wishlist across all your devices and gives you recommendations made for you. Sign in with what you already use: the first time it creates your account, after that it identifies you. No passwords.",
    "Tu cuenta, en un clic. Guarda tu wishlist cross-device.":
        "Your account, in one click. Saves your wishlist cross-device.",
    "Importa tu colección real y calcula tu gap de vinilo.":
        "Import your real collection and calculate your vinyl gap.",
    "Entrar con Discogs": "Sign in with Discogs",
    "Afina las recomendaciones con lo que de verdad escuchas.":
        "Fine-tune recommendations with what you actually listen to.",
    "Entrar con Last.fm": "Sign in with Last.fm",
    "¿Solo quieres guardar discos? No hace falta cuenta: pulsa el ♥ en cualquier disco y va a tu":
        "Just want to save records? No account needed: tap the ♥ on any record and it goes to your",
    "en este navegador.": "in this browser.",
    "Tu cuenta": "Your account",
    "Conexiones": "Connections",
    "Conectada": "Connected",
    "Es tu única forma de entrar. Para eliminarla, borra la cuenta.":
        "It's your only way to sign in. To remove it, delete your account.",
    "Desconectar": "Disconnect",
    "No configurado en este entorno": "Not configured in this environment",
    "No disponible": "Not available",
    "Tu única conexión no se puede desconectar (perderías el acceso). Conecta otra antes, o usa":
        "Your only connection can't be disconnected (you'd lose access). Connect another one first, or use",
    "Borrar cuenta": "Delete account",
    "Preferencias": "Preferences",
    "Tema": "Theme",
    "Claro u oscuro (se recuerda en este navegador).":
        "Light or dark (remembered in this browser).",
    "Tus datos": "Your data",
    "Descargar mis datos": "Download my data",
    "Todo lo que guardamos de ti, en un archivo JSON (perfil, conexiones y wishlist).":
        "Everything we store about you, in a JSON file (profile, connections and wishlist).",
    "Exportar": "Export",
    "Cómo tratamos tus datos:": "How we handle your data:",
    "política de privacidad": "privacy policy",
    "Cerrar sesión": "Sign out",
    "¿Seguro? Se borrará tu cuenta, tu wishlist y tus conexiones. No se puede deshacer.":
        "Are you sure? Your account, your wishlist and your connections will be deleted. This can't be undone.",
    "tu cuenta": "your account",
    # ── wishlist / privacidad / errores ──
    "No encontrado": "Not found",
    "No existe ninguna": "There is no",
    "con el identificador": "with the identifier",
    "Volver al inicio": "Back to home",
    "Algo falló": "Something went wrong",
    "Algo falló por nuestro lado": "Something went wrong on our end",
    "Ha ocurrido un error inesperado. Ya ha quedado registrado; vuelve a intentarlo en un momento.":
        "An unexpected error occurred. It has already been logged; try again in a moment.",
    "Conexión con": "Connection with",
    "No pudimos conectar con": "We couldn't connect with",
    "Reintentar con Google": "Retry with Google",
    "Reintentar con Discogs": "Retry with Discogs",
    "Reintentar con Last.fm": "Retry with Last.fm",
    "Los discos que guardas se conservan en": "The records you save are kept in",
    "este navegador": "this browser",
    "Conecta una cuenta y los llevas a todos tus dispositivos.":
        "Connect an account and take them to all your devices.",
    "Los discos que has guardado, con su precio más barato en tiendas ES.":
        "The records you've saved, with their cheapest price in Spanish shops.",
    "Cargando tu wishlist…": "Loading your wishlist…",
    "Aún no has guardado ningún disco. Pulsa el ♥ en cualquier disco para empezar tu wishlist.":
        "You haven't saved any records yet. Tap the ♥ on any record to start your wishlist.",
    "wishlist": "wishlist",
    "Política de privacidad": "Privacy policy",
    "Última actualización:": "Last updated:",
    "Esta política explica qué datos personales trata": "This policy explains what personal data is handled by",
    "y con qué fin. Vinilogy es una herramienta para descubrir ediciones de vinilo y sus precios en tiendas independientes de España. Puedes usar la mayor parte de la web (buscar, ver fichas, precios, «vibra» y guardar discos con ♥)":
        "and for what purpose. Vinilogy is a tool for discovering vinyl editions and their prices at independent shops in Spain. You can use most of the site (search, view listings, prices, «vibe» and save records with ♥)",
    "sin cuenta": "without an account",
    "Responsable del tratamiento": "Data controller",
    "Contacto:": "Contact:",
    "Qué datos tratamos y con qué base": "What data we handle and on what basis",
    "Uso sin cuenta.": "Use without an account.",
    "La wishlist anónima (♥) se guarda solo en": "The anonymous wishlist (♥) is stored only in",
    "tu navegador": "your browser",
    "(localStorage); no llega a nuestros servidores hasta que inicias sesión y decides fusionarla. El tema claro/oscuro también es local.":
        "(localStorage); it never reaches our servers until you sign in and decide to merge it. The light/dark theme is also local.",
    "Cuenta (opcional).": "Account (optional).",
    "Si te identificas con Google, Discogs o Last.fm guardamos: tu":
        "If you sign in with Google, Discogs or Last.fm we store: your",
    "correo": "email",
    "y nombre para mostrar (Google), el identificador y nombre de usuario en el proveedor, tu":
        "and display name (Google), the identifier and username at the provider, your",
    "y, si conectas Discogs, un valor estimado de tu colección. Base legal:":
        "and, if you connect Discogs, an estimated value of your collection. Legal basis:",
    "ejecución del servicio que solicitas": "performance of the service you request",
    "(art. 6.1.b RGPD).": "(art. 6.1.b GDPR).",
    "Cookie de sesión": "Session cookie",
    "estrictamente necesaria para mantenerte identificado. No usamos cookies de publicidad ni de seguimiento de terceros.":
        "strictly necessary to keep you signed in. We don't use advertising or third-party tracking cookies.",
    "Proveedores de identidad (terceros)": "Identity providers (third parties)",
    "Al conectar Google, Discogs o Last.fm, esos servicios actúan bajo sus propias políticas. A Google solo le pedimos identidad básica (correo y perfil). Los tokens de conexión se usan únicamente para el fin de cada proveedor (colección de Discogs, escucha de Last.fm, identidad de Google) y puedes revocarlos cuando quieras desconectando el proveedor. No vendemos ni cedemos tus datos a terceros con fines comerciales.":
        "When you connect Google, Discogs or Last.fm, those services act under their own policies. From Google we only request basic identity (email and profile). Connection tokens are used solely for each provider's purpose (your Discogs collection, your Last.fm listening, your Google identity) and you can revoke them whenever you want by disconnecting the provider. We don't sell or share your data with third parties for commercial purposes.",
    "Conservación": "Retention",
    "Conservamos tus datos mientras tengas la cuenta activa. Si la borras, se eliminan tu perfil, conexiones, sesiones y wishlist de forma inmediata (en cascada).":
        "We keep your data as long as your account is active. If you delete it, your profile, connections, sessions and wishlist are removed immediately (cascading).",
    "Tus derechos": "Your rights",
    "Puedes ejercer en cualquier momento tus derechos de acceso, portabilidad, rectificación y supresión:":
        "You can exercise your rights of access, portability, rectification and erasure at any time:",
    "Acceso y portabilidad:": "Access and portability:",
    "descarga todos tus datos en JSON desde": "download all your data as JSON from",
    "Exportar mis datos": "Export my data",
    "(requiere sesión).": "(requires sign-in).",
    "Supresión:": "Erasure:",
    "borra tu cuenta y todo lo asociado desde": "delete your account and everything associated from",
    "Para cualquier otra solicitud, escríbenos a": "For any other request, write to us at",
    "También puedes reclamar ante la Agencia Española de Protección de Datos (aepd.es).":
        "You can also file a complaint with the Spanish Data Protection Agency (aepd.es).",
    # ── etiquetas dinámicas del backend (disponibilidad, moods) ──
    "En stock": "In stock",
    "Listado": "Listed",
    "Bajo pedido": "On order",
    "Agotado": "Sold out",
    "Animado / enérgico": "Upbeat / energetic",
    "Cañero / potente": "Hard-hitting / powerful",
    "Domingo lluvioso": "Rainy Sunday",
    "Ensoñador / etéreo": "Dreamy / ethereal",
    "Festivo / baile": "Party / dance",
    "Introspectivo": "Introspective",
    "Jazz de madrugada": "Late-night jazz",
    "Melancólico / triste": "Melancholic / sad",
    "Nostálgico": "Nostalgic",
    "Oscuro / nocturno": "Dark / nocturnal",
    "Psicodélico": "Psychedelic",
    "Relajado / chill": "Relaxed / chill",
    "Romántico": "Romantic",
    "Veraniego / soleado": "Summery / sunny",
}


def resolve_lang(request) -> str:
    """Idioma de la petición: cookie > Accept-Language > DEFAULT."""
    cookie = request.cookies.get(LANG_COOKIE)
    if cookie in SUPPORTED:
        return cookie
    accept = (request.headers.get("accept-language") or "").lower()
    # heurística barata: el primer idioma que reconozcamos gana
    for chunk in accept.replace(" ", "").split(","):
        code = chunk.split(";")[0][:2]
        if code in SUPPORTED:
            return code
    return DEFAULT


def t(text, lang):
    """Traduce `text` al idioma `lang`. ES (o desconocido) → el propio texto."""
    if lang == "en":
        return EN.get(text, text)
    return text
