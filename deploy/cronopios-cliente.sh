#!/usr/bin/env bash
# Cronopios: add a client (or update one) from the server console.
# Installed as /usr/local/bin/cronopios-cliente by cronopios-update.sh.
#   cronopios-cliente "Espacio" correo@cliente.com Nombre [Zona/Horaria]
# Example: cronopios-cliente "Mi Cliente" persona@cliente.com Ana Europe/Madrid
set -euo pipefail
if [ $# -lt 2 ]; then
  echo 'Uso: cronopios-cliente "Espacio" correo@cliente.com Nombre [Zona/Horaria]'
  exit 1
fi
cd /opt/brightbean
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.cronopios.yml"
$COMPOSE exec -T app python manage.py agregar_cliente \
  --espacio "$1" --email "$2" --nombre "${3:-}" --zona "${4:-}" </dev/null
$COMPOSE exec -T app python manage.py asegurar_canales </dev/null || true
