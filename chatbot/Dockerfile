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

# Sin este COPY la imagen queda vacía y solo "funciona" por el bind mount de
# desarrollo (./chatbot:/app en docker-compose.yml). .dockerignore excluye
# secretos y datos generados en runtime para que no queden horneados en la imagen.
COPY --chown=appuser:appuser . .

# CMD "de producción" (sin --reload), para que la imagen arranque sola sin
# bind mount. docker-compose.yml lo sobreescribe con --reload en desarrollo.
#
# --forwarded-allow-ips="": sin esto, uvicorn confía en X-Forwarded-For
# entrante desde loopback y reescribe la IP del cliente con ese header, lo
# que permite evadir el rate limiting de /api/auth/* (chatbot/auth.py)
# rotándolo en cada intento. No hay proxy real delante de este servidor.
#
# EXPOSE 8001: documenta el puerto de uvicorn (convención estándar de Docker;
# Railway detecta el puerto en runtime y no depende de esta instrucción).
EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--forwarded-allow-ips="]
