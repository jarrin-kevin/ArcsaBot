#!/bin/sh
set -e

# Railway monta su Volume vacío en /app/data en el primer arranque, tapando
# lo que la imagen ya tenía en esa ruta (confirmado empíricamente 2026-09-09:
# a diferencia de un volumen Docker plano, un Volume de Railway recién creado
# NO hereda el contenido previo de la imagen en ese path). Por eso
# vector_docstore.json y normativa/ se guardan aparte, en /app/data_seed/
# (ver Dockerfile), y acá se copian a /app/data/ si todavía no están —
# chequeo idempotente, seguro de correr en cada arranque del contenedor.
if [ ! -f /app/data/vector_docstore.json ] && [ -f /app/data_seed/vector_docstore.json ]; then
    echo "[entrypoint] /app/data sin vector_docstore.json: sembrando desde /app/data_seed..."
    cp -r /app/data_seed/. /app/data/
    echo "[entrypoint] Siembra completa."
fi

exec "$@"
