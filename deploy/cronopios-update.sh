#!/usr/bin/env bash
# Cronopios: bring the server up to date with the fork, if it changed.
# Installed as /usr/local/bin/cronopios-update and run every 10 minutes by a
# systemd timer (see cronopios-actualizar.sh). Safe to run by hand.
set -euo pipefail
main() {
  local DIR=/opt/brightbean
  local COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.cronopios.yml"
  cd "$DIR"
  local branch; branch="$(git rev-parse --abbrev-ref HEAD)"
  git fetch -q origin "$branch"
  if [ "$(git rev-parse HEAD)" = "$(git rev-parse "origin/$branch")" ] && [ "${1:-}" != "--force" ]; then
    exit 0
  fi
  echo "== $(date -u) actualizando a $(git rev-parse --short "origin/$branch")"
  git reset -q --hard "origin/$branch"
  $COMPOSE up -d --build </dev/null
  for i in $(seq 1 60); do $COMPOSE exec -T app python manage.py check </dev/null >/dev/null 2>&1 && break; sleep 5; done
  $COMPOSE exec -T app python manage.py asegurar_canales </dev/null || true
  docker image prune -f >/dev/null 2>&1 || true
  echo "== $(date -u) listo"
}
main "$@"
