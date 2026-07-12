# Fase 2 — Cifrado at-rest de tokens OAuth (BORRADOR, sin aplicar)

Cifrar los tokens que **core consume** (Discogs `oauth_token`+`oauth_token_secret`,
Last.fm `session_key`) para que un volcado de DB no entregue credenciales vivas de
terceros. Google ya no se almacena (Fase 1, migración 003).

Requiere coordinar el repo de **core** (lee esos tokens) → hacerlo cuando lo abras,
idealmente junto al pipeline de reresolve. Nada aquí está aplicado.

Piezas:
1. `migrations/004_encrypt_oauth_tokens.sql.draft` — pgcrypto + funciones + backfill.
2. Diff en v2 (`app/db.py`) — cifrar al escribir. **Abajo, sin aplicar.**
3. Cambio en core — descifrar al leer. **Abajo (snippet).**

---

## 1. Gestión de la clave

- **`VINILOGY_TOKENS_KEY`**: secreto largo aleatorio, el **mismo** en el entorno de v2
  y de core. Nunca en el repo, nunca en la DB (así el volcado por sí solo no descifra).
- Generar: `openssl rand -base64 48`
- Guardar: gestor de secretos del hosting / variable de entorno del proceso.
- Rotación: backfill que descifra con la clave vieja y recifra con la nueva
  (`SET col = app_encrypt_token(app_decrypt_token(col, :vieja), :nueva)`).

Diseño **tolerante** (ver funciones en el `.sql.draft`): sin clave → passthrough en
claro; al leer solo se descifra lo que está PGP-armored. Esto permite convivir con
filas mixtas y hace que el código de v2 se pueda mergear **antes** que la migración
sin romper nada (el cifrado "se enciende" al fijar la clave + aplicar la migración).

---

## 2. Diff en v2 — `app/db.py`

Leer la clave del entorno una vez (junto a las demás constantes de módulo, p.ej. cerca
de `STORE_FRESHNESS_MAX_DAYS`):

```python
# Clave de cifrado de tokens OAuth (Fase 2). Ausente → se escribe en claro
# (app_encrypt_token hace passthrough). Debe coincidir con la de core.
_TOKENS_KEY = os.environ.get("VINILOGY_TOKENS_KEY") or None
```

En `upsert_oauth_credential`, envolver los tokens con `app_encrypt_token(...)` en el
`VALUES` y pasar la clave como parámetro. Solo cambia el bloque `VALUES` y el dict de
params; el `ON CONFLICT DO UPDATE SET ... = EXCLUDED.<col>` **no se toca** (EXCLUDED ya
trae el valor cifrado):

```diff
             VALUES
                 (%(uid)s, %(p)s::oauth_provider, %(acc)s, %(uname)s,
-                 %(tok)s, %(sec)s, %(skey)s,
-                 %(a2t)s, %(a2r)s, %(a2e)s, now())
+                 app_encrypt_token(%(tok)s,  %(key)s),
+                 app_encrypt_token(%(sec)s,  %(key)s),
+                 app_encrypt_token(%(skey)s, %(key)s),
+                 %(a2t)s, %(a2r)s, %(a2e)s, now())
```
```diff
             {"uid": user_id, "p": provider, "acc": str(provider_account_id),
              "uname": provider_username, "tok": oauth_token,
              "sec": oauth_token_secret, "skey": session_key,
-             "a2t": oauth2_access_token, "a2r": oauth2_refresh_token,
-             "a2e": oauth2_expires_at},
+             "a2t": oauth2_access_token, "a2r": oauth2_refresh_token,
+             "a2e": oauth2_expires_at, "key": _TOKENS_KEY},
```

Notas:
- `a2t`/`a2r` (Google) son siempre `None` tras la Fase 1 → no se cifran (no hay nada).
- `app_encrypt_token` vive en la DB (creada por la migración 004), así que v2 y core
  comparten exactamente el mismo esquema. No hacen falta dependencias nuevas en v2.

---

## 3. Cambio en core (repo aparte) — leer descifrando

Donde core lea estos tokens para sincronizar, envolver la columna con
`app_decrypt_token(col, :key)` y pasar `VINILOGY_TOKENS_KEY`:

```sql
SELECT app_decrypt_token(oauth_token,        :tokens_key) AS oauth_token,
       app_decrypt_token(oauth_token_secret, :tokens_key) AS oauth_token_secret,
       app_decrypt_token(session_key,        :tokens_key) AS session_key
  FROM user_oauth_credentials
 WHERE ...
```

Como `app_decrypt_token` solo descifra lo armored y devuelve el resto tal cual, core
puede desplegar este cambio **antes o después** del backfill sin romperse.

---

## 4. Orden de despliegue

Gracias al diseño tolerante el orden es flexible, pero el recomendado:

1. **Clave** `VINILOGY_TOKENS_KEY` en el entorno de v2 y de core (mismo valor).
2. **Aplicar migración 004** a core (crea pgcrypto + funciones + backfill de las filas
   en claro). A partir de aquí las filas heredadas quedan cifradas.
3. **Desplegar core** con la lectura vía `app_decrypt_token`.
4. **Desplegar v2** con el diff de escritura (`app_encrypt_token`).

Los pasos 3 y 4 pueden ir en cualquier orden respecto al 2 (tolerancia a filas
mixtas). El único requisito duro: la clave debe existir en el entorno **antes** de que
la migración/backfill se ejecute con ella.

---

## 5. Rollback

- Volver a claro (si hiciera falta): `UPDATE ... SET col =
  app_decrypt_token(col, :key)` para las tres columnas, luego revertir el diff de v2 y
  la lectura de core. Las funciones pueden quedarse (passthrough sin clave).
- Revertir solo código (dejando datos cifrados) NO es seguro: core leería armored sin
  descifrar. Si reviertes, revierte datos también.

---

## 6. Verificación tras aplicar

- `SELECT app_decrypt_token(oauth_token, :key) ...` devuelve los tokens en claro.
- `SELECT oauth_token FROM user_oauth_credentials WHERE provider='discogs'` muestra
  `-----BEGIN PGP MESSAGE-----...` (cifrado en reposo).
- Reconectar Discogs/Last.fm en la app y confirmar que core sigue sincronizando
  (colección / escucha) leyendo vía `app_decrypt_token`.
- El CHECK `user_oauth_creds_shape` sigue satisfecho (el ciphertext es NOT NULL).
