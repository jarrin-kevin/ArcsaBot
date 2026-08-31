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
#RUN adduser --disabled-password --gecos "" appuser && chown -R appuser:appuser /app
#USER appuser

# Copia el resto del código de la aplicación al contenedor asignándolo al usuario creado
#COPY --chown=appuser:appuser . .

CMD ["python", "main.py"]
