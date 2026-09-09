# Guía de despliegue: backend en Railway + frontend en Vercel

Esta guía cubre el despliegue de producción de RagChatbot:

- **Backend** (`chatbot/`, FastAPI + Pinecone + Gemini): Railway, usando el
  `chatbot/Dockerfile` ya existente.
- **Frontend** (`frontend/`, React + Vite): Vercel.

Ningún paso de esta guía puede automatizarse desde el repo: crear cuentas,
pegar API keys en dashboards de terceros y conectar OAuth con GitHub son
acciones que solo el usuario puede hacer. Esta guía es la referencia exacta
de qué hacer, en qué orden y con qué valores.

## Orden recomendado

1. **Backend primero** (Railway): necesitás su URL pública real antes de
   configurar el frontend.
2. **Frontend después** (Vercel): usa esa URL como `VITE_API_URL`.
3. Volvés a Railway para completar `CORS_ORIGINS` con el dominio real que
   Vercel te asignó (hay una dependencia circular ahí: el backend necesita
   saber la URL del frontend para CORS, y eso solo existe después del paso 2).

---

## 0. Antes de empezar: hallazgos relevantes del repo

Investigación hecha sobre el código actual (no hace falta volver a
verificarla):

- **La URL del backend en el frontend YA es configurable.** No estaba
  hardcodeada a `localhost:8001`: los 3 lugares que hablan con el backend
  (`frontend/src/services/transport/HttpChatTransport.js`,
  `frontend/src/services/transport/ChatStore.js`,
  `frontend/src/context/AuthContext.jsx`) ya leen
  `import.meta.env.VITE_API_URL` con fallback a `http://localhost:8001`. La
  variable a configurar en Vercel es **`VITE_API_URL`** (no
  `VITE_API_BASE_URL` — ese nombre no existe en el código, y como la
  convención ya está establecida y consistente en 3 archivos, no se tocó ni
  se renombró nada).
- **El frontend no usa router de client-side routing.** No hay
  `react-router` ni ninguna librería de rutas en `frontend/package.json`;
  `frontend/src/App.jsx` cambia de vista (`chat` / `profile` / `help`) con
  `useState`, no con URLs. Por eso **no hace falta `vercel.json`**: no hay
  rutas tipo `/perfil` que puedan dar 404 al refrescar, porque no existen
  URLs internas. Si en el futuro se agrega un router con URLs propias, ahí sí
  va a hacer falta un `vercel.json` con un rewrite catch-all a `index.html`.
- **`chatbot/Dockerfile` ya estaba listo para producción en casi todo:**
  el `CMD` ya es el de producción (sin `--reload`) y ya tiene
  `--forwarded-allow-ips=""` puesto (mitigación de un bypass real de rate
  limiting vía `X-Forwarded-For`, ver el comentario en el propio Dockerfile).
  Lo único que faltaba era el `EXPOSE 8001`, que se agregó (ver sección 3).
- **Falta una variable de entorno crítica en la lista original:**
  `chatbot/auth.py` requiere `AUTH_SECRET_KEY` y **corta la ejecución del
  proceso** (`raise SystemExit(1)`) si no está seteada — el backend ni
  siquiera arranca sin ella. No estaba en la lista de variables a configurar
  en Railway; se agregó abajo. Ojo: tampoco está declarada en
  `docker-compose.yml` (que solo pasa `GEMINI_API_KEY` y
  `PINECONE_API_KEY` al contenedor), así que si el entorno local depende de
  un `.env` en la raíz del repo cargado fuera de Docker, conviene confirmar
  cómo se está inyectando hoy en local también — pero eso es un tema aparte
  de este despliegue.
- **`chatbot/data/` no viaja ni en git ni en la imagen de Docker**
  (`.gitignore` y `chatbot/.dockerignore` la excluyen a propósito, para no
  hornear cientos de MB en la imagen). Ahí vive `users.db` (se recrea solo,
  no hay problema) pero también `vector_docstore.json` y `normativa/`,
  que son el mapeo local id-de-Pinecone → texto/metadata real de cada chunk.
  Sin ellos, el backend **no crashea** (`_load_docstore()` en
  `chatbot/main.py` devuelve un diccionario vacío si el archivo no existe),
  pero el RAG queda funcionalmente roto: no puede resolver el contenido de
  ningún resultado de Pinecone, así que la mayoría de las respuestas van a
  caer en el mensaje de "no se encontró evidencia suficiente". Ver la nota
  en la sección 1.5 sobre cómo poblar el Volume con estos datos.

---

## 1. Backend en Railway

### 1.1. Cuenta y conexión del repo

1. Entrá a [railway.com](https://railway.com) y creá una cuenta (podés
   loguearte directo con tu cuenta de GitHub).
2. **New Project → Deploy from GitHub repo** → autorizá el acceso de Railway
   a tu repo `RagChatbot` (u organización) si te lo pide, y seleccionalo.

### 1.2. Root Directory = `chatbot`

Esto es **exclusivamente un setting del dashboard**: se investigó si
`railway.json`/`railway.toml` podían declarar el Root Directory de forma
declarativa, y no es posible — el "config-as-code" de Railway solo cubre las
secciones `build` y `deploy` (comando de build, Dockerfile path, healthcheck,
restart policy, etc.), pero **no** el Root Directory del servicio. Por eso no
se agregó ningún `railway.json` al repo — habría sido un archivo sin efecto
real.

Pasos manuales:

1. En el servicio recién creado, andá a **Settings → Source**.
2. En **Root Directory**, poné `chatbot`.
3. Guardá. Railway va a detectar automáticamente el archivo `chatbot/Dockerfile`
   (busca un archivo llamado exactamente `Dockerfile` en la raíz del Root
   Directory configurado) y va a usar el builder Docker sin que haga falta
   nada más.

### 1.3. Puerto público (networking)

`chatbot/Dockerfile` ahora tiene `EXPOSE 8001` (se agregó, ver sección 3),
pero es importante entender qué hace y qué no hace en Railway:

- Railway **no lee la instrucción `EXPOSE`** del Dockerfile para decidir a
  qué puerto rutear. Lo que hace es "magic port detection": cuando generás
  un dominio público para el servicio (**Settings → Networking → Generate
  Domain**), Railway detecta automáticamente en qué puerto está escuchando
  el proceso que ya está corriendo y lo usa como target port. Como el `CMD`
  de este Dockerfile escucha siempre en `8001` (puerto fijo, no lee
  `$PORT`), esa detección automática debería resolver sola a `8001`.
- Si después de generar el dominio el healthcheck o las requests fallan,
  entrá a **Settings → Networking** y fijá el target port a `8001` a mano
  (Railway lo permite si detecta más de un puerto o si la detección
  automática no encuentra ninguno).
- No hizo falta modificar el `CMD` para leer `$PORT` (que sería lo
  "idiomático" en Railway): el `CMD` usa forma exec (`CMD ["uvicorn", ...]`),
  que no expande variables de entorno tipo `${PORT}` — para eso habría que
  pasar a forma shell, lo que cambia cómo se propagan las señales de
  apagado (SIGTERM) al proceso de uvicorn. Es un cambio de más riesgo del
  que pedía esta tarea, así que se dejó el puerto fijo + magic port
  detection, que es un patrón soportado.

### 1.4. Volume para persistencia (`/app/data`)

Sin esto, `chatbot/data/users.db` (usuarios y conversaciones) se borra en
cada redeploy o reinicio, porque Railway no persiste el filesystem del
contenedor por defecto.

1. En el servicio, pestaña **Volumes** (o desde el canvas del proyecto,
   botón para agregar un Volume) → **Attach Volume**.
2. Mount path: `/app/data` (coincide con `CHATBOT_DIR / "data"` que usa
   `chatbot/main.py`, `chatbot/auth.py` y `chatbot/conversations.py` —
   `CHATBOT_DIR` es `/app` porque el `WORKDIR` del Dockerfile es `/app`).

### 1.5. Permisos del Volume (`RAILWAY_RUN_UID`)

Los Volumes de Railway se montan como usuario `root`, pero el contenedor
corre como `appuser` (usuario sin privilegios, creado en el Dockerfile por
seguridad). Sin este ajuste, `appuser` no puede escribir en `/app/data` y
todo lo que dependa de esa carpeta (login, signup, historial) va a fallar.

- Variable de entorno a agregar: `RAILWAY_RUN_UID` = `0`.

### 1.6. Poblar el Volume con los datos del RAG (paso importante, no automatizable desde acá)

Como se explica en la sección 0, `chatbot/data/vector_docstore.json` y
`chatbot/data/normativa/` no están ni en git ni en la imagen. El Volume
arranca vacío. Dos formas de resolverlo (elegí una):

**Opción A (recomendada para el primer deploy):**
Antes de la primera build en Railway, comentá temporalmente la línea `data/`
de `chatbot/.dockerignore` para que `COPY --chown=appuser:appuser . .` sí
incluya el `chatbot/data/` local actual (con `vector_docstore.json` y
`normativa/` ya generados) en la imagen. Es un comportamiento estándar de
Docker que cuando montás un Volume vacío sobre un path que ya tenía
contenido en la imagen, ese contenido se copia al Volume en el primer
arranque del contenedor. Después de confirmar que el primer deploy levantó
bien y respondió una consulta real con citas (no solo el `/health`), volvé a
excluir `data/` en `.dockerignore` para los próximos builds — el Volume ya
va a conservar los datos independientemente de la imagen.

*Nota:* este comportamiento de "seed" inicial es un comportamiento estándar
de volúmenes Docker; no está documentado explícitamente por Railway para su
implementación de Volumes, así que conviene verificarlo después del primer
deploy (ver checklist al final) en vez de asumirlo a ciegas.

**Opción B (si la A no funciona o preferís no tocar el `.dockerignore`):**
Usá `railway ssh` (accesible desde **Settings** del servicio, botón "Copy
SSH Command", o `railway ssh` con la CLI instalada y el proyecto linkeado)
para entrar a una shell dentro del contenedor ya desplegado y confirmar qué
hay en `/app/data`. Desde ahí podés, por ejemplo, volver a correr el proceso
de ingesta (`vector_ingest.py`, con `PINECONE_API_KEY`/`GEMINI_API_KEY` ya
seteadas como env vars del servicio) para regenerar `vector_docstore.json`
directamente sobre el Volume montado.

### 1.7. Variables de entorno del servicio

En **Variables**, agregá:

| Variable | Valor | Notas |
|---|---|---|
| `GEMINI_API_KEY` | tu API key real de Gemini | requerida, `chatbot/main.py` corta si falta |
| `PINECONE_API_KEY` | tu API key real de Pinecone | requerida, `chatbot/vector_store.py` corta si falta |
| `AUTH_SECRET_KEY` | un secreto random largo (ej. `openssl rand -hex 32`) | **requerida** — `chatbot/auth.py` corta el proceso si falta. No estaba en la lista original, se detectó al revisar el código |
| `RAILWAY_RUN_UID` | `0` | para que `appuser` pueda escribir en el Volume (ver 1.5) |
| `CORS_ORIGINS` | por ahora dejalo vacío o con un valor provisorio; se completa en el paso 4 con la URL real de Vercel | `chatbot/main.py` usa un default de orígenes `localhost` si no está seteada, así que el deploy no se rompe por no tenerla todavía |

Guardá — Railway redeploya solo al cambiar variables.

### 1.8. Generar el dominio y guardar la URL

**Settings → Networking → Generate Domain**. Copiá la URL
(`https://<algo>.up.railway.app` o similar) — la vas a necesitar en el paso
del frontend.

### 1.9. Dominio propio (opcional, a futuro)

Railway soporta dominios custom, pero **solo en planes pagos** (no hay free
tier permanente, son $5 de crédito por 30 días y después un piso de
~$5/mes). Cuando lo tengas: **Settings → Networking → Custom Domain**,
agregá el dominio y configurá el registro CNAME/A que te indique Railway en
el DNS de tu proveedor de dominio.

---

## 2. Frontend en Vercel

### 2.1. Cuenta y conexión del repo

1. Entrá a [vercel.com](https://vercel.com), creá una cuenta (podés
   loguearte con GitHub).
2. **Add New → Project** → importá el mismo repo de GitHub.

### 2.2. Configuración del build

Vercel detecta automáticamente Vite por `frontend/package.json` (scripts
`dev`/`build`/`preview` con `vite`), así que no hace falta ningún
`vercel.json` para esto (y, como se explica en la sección 0, tampoco hace
falta uno para SPA routing porque el proyecto no usa client-side routing
todavía).

En la pantalla de configuración del proyecto:

- **Root Directory**: `frontend`
- **Framework Preset**: Vite (debería autodetectarse al fijar el Root
  Directory de arriba)
- **Build Command** / **Output Directory**: dejar los defaults de Vite
  (`vite build` / `dist`)

### 2.3. Variable de entorno

En **Environment Variables** del proyecto:

- `VITE_API_URL` = la URL real que te dio Railway en el paso 1.8 (ej.
  `https://ragchatbot-backend-production.up.railway.app`, **sin** slash
  final).
- Marcala al menos para **Production** (y Preview, si querés que los
  preview deployments también hablen con el backend real).

**Importante:** Vite "hornea" las variables `VITE_*` en el bundle en tiempo
de build, no las lee en runtime. Si cambiás `VITE_API_URL` después de un
deploy ya hecho, tenés que forzar un **Redeploy** en Vercel para que el
nuevo valor tenga efecto — guardar la variable sola no alcanza.

### 2.4. Deploy

Con eso, dale **Deploy**. Al terminar, Vercel te da una URL tipo
`https://<proyecto>.vercel.app`.

### 2.5. Dominio propio (opcional, a futuro)

**Project Settings → Domains**, agregá tu dominio y seguí las instrucciones
de DNS que te da Vercel (A/CNAME). Vercel sí ofrece esto en su plan
gratuito (a diferencia de Railway).

---

## 3. Volver a Railway: cerrar el círculo de CORS

Con la URL real de Vercel ya generada (paso 2.4, y el dominio propio si lo
configuraste en 2.5):

1. Volvé a Railway → tu servicio de backend → **Variables**.
2. Seteá `CORS_ORIGINS` con la(s) URL(s) exacta(s) del frontend, separadas
   por coma si son varias (ej. producción + dominio propio), sin slash
   final:
   ```
   CORS_ORIGINS=https://tu-proyecto.vercel.app,https://tudominio.com
   ```
3. Guardá — Railway redeploya solo. `chatbot/main.py` corta el arranque si
   `CORS_ORIGINS` contiene `*` (por la combinación con `allow_credentials=True`
   que usa el token Bearer de auth), así que asegurate de listar orígenes
   exactos, nunca un wildcard.

---

## 4. Checklist final de verificación

- [ ] `GET https://<tu-backend>.up.railway.app/health` responde `{"status": "ok"}`.
- [ ] El frontend en Vercel carga y el login/signup funciona (confirma que
      `AUTH_SECRET_KEY` y el Volume están bien configurados).
- [ ] Una consulta real al chat devuelve una respuesta con fuentes citadas,
      no el mensaje de "no se encontró evidencia suficiente" en todas las
      preguntas (confirma que `vector_docstore.json`/`normativa/` sí están
      en el Volume, ver sección 1.6).
- [ ] Recargar la página después de loguearte no rompe la sesión ni tira
      errores de CORS en la consola del navegador (confirma que
      `CORS_ORIGINS` tiene la URL exacta de Vercel).
- [ ] Cerrar sesión y volver a entrar conserva el historial de
      conversaciones después de un rato (confirma que el Volume persiste
      entre requests/reinicios, no solo dentro de la misma sesión de
      contenedor).

## Resumen de archivos tocados/creados para esta guía

- `chatbot/Dockerfile`: se agregó `EXPOSE 8001` (documentación del puerto;
  no cambia comportamiento en runtime, ver sección 1.3).
- `DEPLOY.md`: este archivo.
- No se creó `railway.json`/`railway.toml` (Root Directory es dashboard-only,
  ver sección 1.2).
- No se creó `frontend/vercel.json` (no hay client-side routing, ver
  sección 0).
- No se tocó ningún código de `frontend/src/services/transport/` ni
  `frontend/src/context/AuthContext.jsx`: `VITE_API_URL` ya era
  configurable.
