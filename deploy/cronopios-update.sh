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
  # Keep the installed commands current, even when nothing else changed.
  install -m 0755 deploy/cronopios-cliente.sh /usr/local/bin/cronopios-cliente 2>/dev/null || true
  if [ "$(git rev-parse HEAD)" = "$(git rev-parse "origin/$branch")" ] && [ "${1:-}" != "--force" ]; then
    exit 0
  fi
  echo "== $(date -u) actualizando a $(git rev-parse --short "origin/$branch")"
  git reset -q --hard "origin/$branch"
  install -m 0755 deploy/cronopios-cliente.sh /usr/local/bin/cronopios-cliente
  # The whole script is already read (main below), so replacing it is safe.
  install -m 0755 deploy/cronopios-update.sh /usr/local/bin/cronopios-update
  install -m 0755 deploy/cronopios-dominio.sh /usr/local/bin/cronopios-dominio
  # Morning email (08:00 Argentina) with what has to be published by hand today.
  cat > /etc/systemd/system/cronopios-aviso.service <<UNIT
[Unit]
Description=Aviso de lo que hay que publicar a mano hoy
After=docker.service

[Service]
Type=oneshot
WorkingDirectory=$DIR
ExecStart=/usr/bin/docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.cronopios.yml exec -T app python manage.py aviso_publicar
UNIT
  cat > /etc/systemd/system/cronopios-aviso.timer <<UNIT
[Unit]
Description=Aviso diario de publicación manual

[Timer]
OnCalendar=*-*-* 08:00:00 America/Argentina/Cordoba
Persistent=true

[Install]
WantedBy=timers.target
UNIT
  systemctl daemon-reload && systemctl enable --now cronopios-aviso.timer >/dev/null 2>&1 || true
  # The website: until there is a domain it lives at sitio.<portal address>.
  if [ -z "$(python3 deploy/cronopios-env.py get SITE_DOMAIN)" ]; then
    python3 deploy/cronopios-env.py set "SITE_DOMAIN=sitio.$(python3 deploy/cronopios-env.py get APP_DOMAIN)"
  fi
  $COMPOSE up -d --build </dev/null
  # The Caddyfile is mounted as a directory; pick up its changes.
  $COMPOSE exec -T caddy caddy reload --config /etc/caddy/Caddyfile </dev/null || true
  for i in $(seq 1 60); do $COMPOSE exec -T app python manage.py check </dev/null >/dev/null 2>&1 && break; sleep 5; done
  $COMPOSE exec -T app python manage.py asegurar_canales </dev/null || true
  docker image prune -f >/dev/null 2>&1 || true
  echo "== $(date -u) listo"
}
main "$@"
