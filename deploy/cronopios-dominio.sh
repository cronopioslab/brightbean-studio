#!/usr/bin/env bash
# Cronopios: move the website and the portal to the agency's own domain.
#   cronopios-dominio ejemplo.com
# Afterwards: https://ejemplo.com (website, www. redirects there) and
# https://portal.ejemplo.com (portal). The old portal address keeps working,
# so links in emails already sent do not break.
# Before running it, the domain's DNS needs three "A" records pointing to this
# server's IP: @ (ejemplo.com), www and portal. Add --forzar to skip the check.
set -euo pipefail
main() {
  local D="${1:-}" FORCE="${2:-}"
  D="$(echo "$D" | tr 'A-Z' 'a-z' | sed -E 's#^https?://##; s#/.*$##; s#^www\.##')"
  if [ -z "$D" ] || [[ "$D" != *.* ]]; then
    echo 'Uso: cronopios-dominio ejemplo.com'; exit 1
  fi
  cd /opt/brightbean
  local ENVPY="python3 deploy/cronopios-env.py"
  local IP; IP="$(curl -fsS http://169.254.169.254/hetzner/v1/metadata/public-ipv4 2>/dev/null || curl -fsS -4 https://ifconfig.me)"

  local ok=1
  for h in "$D" "www.$D" "portal.$D"; do
    if getent ahostsv4 "$h" | awk '{print $1}' | grep -qx "$IP"; then
      echo "OK   $h apunta a este servidor ($IP)"
    else
      echo "FALTA $h todavía no apunta a $IP"; ok=0
    fi
  done
  if [ "$ok" = 0 ] && [ "$FORCE" != "--forzar" ]; then
    echo
    echo "En el panel donde compraste el dominio, crea tres registros tipo A con el valor $IP:"
    echo "  @  (o $D)    www    portal"
    echo "Los cambios de DNS pueden tardar de minutos a unas horas. Después vuelve a correr este comando."
    exit 1
  fi

  local old aliases
  old="$($ENVPY get APP_DOMAIN)"
  aliases="$($ENVPY get APP_ALIASES)"
  if [ -n "$old" ] && [ "$old" != "portal.$D" ] && [[ " $aliases " != *" $old "* ]]; then
    aliases="$(echo "$aliases $old" | xargs)"
  fi
  local hosts="portal.$D"
  for a in $aliases; do hosts="$hosts,$a"; done

  $ENVPY set "SITE_DOMAIN=$D" "APP_DOMAIN=portal.$D" "APP_ALIASES=$aliases" \
             "ALLOWED_HOSTS=$hosts" "APP_URL=https://portal.$D"

  local COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.cronopios.yml"
  $COMPOSE up -d --force-recreate app worker caddy </dev/null
  for i in $(seq 1 60); do $COMPOSE exec -T app python manage.py check </dev/null >/dev/null 2>&1 && break; sleep 5; done
  echo
  echo "Listo. En unos minutos (mientras se emiten los certificados):"
  echo "  Página: https://$D"
  echo "  Portal: https://portal.$D"
  [ -n "$aliases" ] && echo "  Siguen funcionando: $aliases"
}
main "$@"
