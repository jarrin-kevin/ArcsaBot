FROM python:3.11-slim

# Evita que Python escriba archivos .pyc en el disco
ENV PYTHONDONTWRITEBYTECODE=1
# Evita que Python guarde en búfer stdout y stderr (útil para logs en tiempo real)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Crea un usuario sin privilegios de root por seguridad
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser:appuser /app
USER appuser

# Copia el resto del código de la aplicación al contenedor asignándolo al usuario creado.
# Sin este COPY la imagen queda vacía y solo "funciona" gracias al bind mount de
# desarrollo (./chatbot:/app en docker-compose.yml); una imagen subida a un registro
# y corrida sin ese bind mount (p. ej. Cloud Run/GKE) fallaría porque /app no
# tendría main.py. .dockerignore excluye secretos y datos generados en runtime
# (chatbot/secrets/, chatbot/data/) para que no queden horneados en la imagen.
COPY --chown=appuser:appuser . .

# Copia aparte de los datos de referencia del RAG a una ruta que el Volume de
# Railway no toca (/app/data_seed, distinto de /app/data). Ver
# docker-entrypoint.sh para el porqué: un Volume de Railway montado en
# /app/data arranca vacío y tapa lo que el COPY de arriba ya puso ahí, así
# que se necesita esta copia de respaldo para poder "sembrarla" en el primer
# arranque del contenedor.
COPY --chown=appuser:appuser data/vector_docstore.json data/normativa /app/data_seed/

COPY --chown=appuser:appuser docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# main.py es un servidor FastAPI real que se ejecuta con uvicorn. Este CMD
# NO usa --reload: es el comando "de producción", pensado para que la imagen
# arranque sola (sin bind mount) y responda /health tal cual, por ejemplo en
# Cloud Run/GKE. El hot-reload de desarrollo se preserva en docker-compose.yml,
# que sobreescribe este CMD con `command: [... "--reload"]` cuando monta
# ./chatbot:/app.
#
# --forwarded-allow-ips="": uvicorn trae su ProxyHeadersMiddleware activo por
# defecto con trusted_hosts="127.0.0.1", así que confía ciegamente en un
# X-Forwarded-For entrante si el request llega desde loopback (típico detrás
# de un reverse proxy local) y reescribe la IP del cliente con lo que diga
# ese header. Como no hay ningún proxy real delante de este servidor, eso
# permitía evadir por completo el rate limiting de /api/auth/login|signup
# (chatbot/auth.py) mandando un X-Forwarded-For distinto en cada intento
# (encontrado con fuzzing real). Con la lista vacía, uvicorn no confía en
# ese header viniendo de nadie. Si en el futuro se agrega un proxy real
# delante (nginx, load balancer), esto hay que reconfigurarlo con la IP real
# de ese proxy, no dejarlo en "".
#
# EXPOSE 8001: documenta el puerto real en el que escucha uvicorn. Railway NO
# lee esta instrucción para el ruteo (su "magic port detection" detecta el
# puerto en el que el proceso ya está escuchando al generar el dominio), pero
# sí es la convención estándar de Docker y la usan otras plataformas
# (Cloud Run/GKE) para saber qué puerto exponer. Ver DEPLOY.md para el detalle
# de cómo Railway resuelve el puerto público de este servicio.
EXPOSE 8001

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--forwarded-allow-ips="]
