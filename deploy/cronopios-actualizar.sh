#!/usr/bin/env bash
# Cronopios: install automatic updates on a server set up with
# cronopios-setup.sh, and update it right away. Run once, as root:
#   curl -fsSL https://raw.githubusercontent.com/cronopioslab/brightbean-studio/cronopios/portal-es/deploy/cronopios-actualizar.sh | bash
set -euo pipefail
main() {
  local DIR=/opt/brightbean
  cd "$DIR"
  git fetch -q origin && git reset -q --hard "origin/$(git rev-parse --abbrev-ref HEAD)"
  install -m 0755 deploy/cronopios-update.sh /usr/local/bin/cronopios-update
  cat > /etc/systemd/system/cronopios-update.service <<UNIT
[Unit]
Description=Actualiza el portal de Cronopios desde GitHub
After=network-online.target docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/cronopios-update
StandardOutput=append:/var/log/cronopios-update.log
StandardError=append:/var/log/cronopios-update.log
UNIT
  cat > /etc/systemd/system/cronopios-update.timer <<UNIT
[Unit]
Description=Revisa cada 10 minutos si hay cambios en el portal

[Timer]
OnBootSec=5min
OnUnitActiveSec=10min

[Install]
WantedBy=timers.target
UNIT
  systemctl daemon-reload
  systemctl enable --now cronopios-update.timer
  if [ -z "${SKIP_UPDATE:-}" ]; then /usr/local/bin/cronopios-update --force </dev/null; fi
  echo "Actualizaciones automáticas activadas."
}
main "$@"
