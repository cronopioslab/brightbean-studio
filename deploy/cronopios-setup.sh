#!/usr/bin/env bash
# Cronopios: one-shot install of this fork on a fresh Ubuntu 24.04 VPS.
#
# Run as root (for example from the server's cloud-init "user data") with these
# variables set. Secrets are passed in, never stored in this repository:
#   ADMIN_EMAIL      the agency owner's login
#   ADMIN_PASSWORD   their password (12+ characters)
#   SMTP_USER        Gmail address that sends the emails
#   SMTP_PASSWORD    a Gmail app password for that address
# Optional:
#   APP_DOMAIN       defaults to <public-ip>.sslip.io (free HTTPS name, no domain needed)
#   FIRST_CLIENT     name of the first client workspace (default: "Cliente")
#   REPO_URL, REPO_BRANCH
set -euo pipefail

: "${ADMIN_EMAIL:?}" "${ADMIN_PASSWORD:?}" "${SMTP_USER:?}" "${SMTP_PASSWORD:?}"
REPO_URL="${REPO_URL:-https://github.com/cronopioslab/brightbean-studio.git}"
REPO_BRANCH="${REPO_BRANCH:-cronopios/portal-es}"
FIRST_CLIENT="${FIRST_CLIENT:-Cliente}"
DIR=/opt/brightbean
LOG=/root/cronopios-setup.log
exec > >(tee -a "$LOG") 2>&1
echo "== Cronopios setup $(date -u)"

# Swap: building the image needs more than the RAM of a small server.
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

apt-get update -y
apt-get install -y ca-certificates curl git python3 ufw unattended-upgrades
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh

ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable

IP="$(curl -fsS http://169.254.169.254/hetzner/v1/metadata/public-ipv4 2>/dev/null || curl -fsS -4 https://ifconfig.me)"
APP_DOMAIN="${APP_DOMAIN:-${IP//./-}.sslip.io}"

[ -d "$DIR/.git" ] || git clone --branch "$REPO_BRANCH" "$REPO_URL" "$DIR"
cd "$DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  PG_PASSWORD="$(openssl rand -hex 24)"
  APP_DOMAIN="$APP_DOMAIN" PG_PASSWORD="$PG_PASSWORD" python3 - <<'PY'
import os, re, secrets
p = ".env"; s = open(p).read()
v = {
    "SECRET_KEY": secrets.token_urlsafe(64),
    "ENCRYPTION_KEY_SALT": secrets.token_urlsafe(32),
    "DEBUG": "false",
    "ALLOWED_HOSTS": os.environ["APP_DOMAIN"],
    "APP_URL": "https://" + os.environ["APP_DOMAIN"],
    "APP_DOMAIN": os.environ["APP_DOMAIN"],
    "POSTGRES_PASSWORD": os.environ["PG_PASSWORD"],
    "DATABASE_URL": "postgres://postgres:%s@postgres:5432/brightbean" % os.environ["PG_PASSWORD"],
    "SIGNUP_MODE": "closed",
    "EMAIL_BACKEND_TYPE": "smtp",
    "EMAIL_HOST": "smtp.gmail.com",
    "EMAIL_PORT": "587",
    "EMAIL_USE_TLS": "true",
    "EMAIL_HOST_USER": os.environ["SMTP_USER"],
    "EMAIL_HOST_PASSWORD": os.environ["SMTP_PASSWORD"],
    "DEFAULT_FROM_EMAIL": "Cronopios Lab <%s>" % os.environ["SMTP_USER"],
}
for k, val in v.items():
    line = "%s=%s" % (k, val)
    s, n = re.subn(r"^#?\s*%s=.*$" % k, lambda m: line, s, count=1, flags=re.M)
    if not n:
        s += "\n" + line + "\n"
open(p, "w").write(s)
PY
  chmod 600 .env
fi

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.cronopios.yml"
$COMPOSE up -d --build

echo "== waiting for the app"
for i in $(seq 1 60); do $COMPOSE exec -T app python manage.py check >/dev/null 2>&1 && break; sleep 5; done

ADMIN_EMAIL="$ADMIN_EMAIL" ADMIN_PASSWORD="$ADMIN_PASSWORD" FIRST_CLIENT="$FIRST_CLIENT" \
$COMPOSE exec -T -e ADMIN_EMAIL -e ADMIN_PASSWORD -e FIRST_CLIENT app python manage.py shell -c '
import os
from django.utils import timezone
from apps.accounts.models import User
from apps.accounts.signals import provision_organization_and_workspace
from apps.members.models import OrgMembership
from apps.social_accounts.models import SocialAccount
email = os.environ["ADMIN_EMAIL"]
u = User.objects.filter(email=email).first()
if u is None:
    u = User.objects.create_superuser(email=email, password=os.environ["ADMIN_PASSWORD"])
u.tos_accepted_at = u.tos_accepted_at or timezone.now()
u.save()
provision_organization_and_workspace(u)
org = OrgMembership.objects.get(user=u).organization
org.name = "Cronopios Lab"; org.default_timezone = "America/Argentina/Cordoba"; org.save()
ws = org.workspaces.order_by("created_at").first()
if ws.name == "My Workspace":
    ws.name = os.environ["FIRST_CLIENT"]
ws.approval_workflow_mode = "required_internal_and_client"
ws.save()
SocialAccount.objects.get_or_create(
    workspace=ws, platform="instagram",
    account_platform_id=SocialAccount.VALIDATION_PLACEHOLDER_PREFIX + "instagram",
    defaults={"account_name": "Instagram (validación)", "connection_status": "connected"},
)
print("ok", org.name, ws.name)
'

cat > /root/cronopios-listo.txt <<EOF
BrightBean de Cronopios instalado.
Entrar en: https://$APP_DOMAIN
Usuario: $ADMIN_EMAIL
Registro: $LOG
EOF
cat /root/cronopios-listo.txt
