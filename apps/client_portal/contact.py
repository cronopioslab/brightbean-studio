"""Cronopios: the contact form of the agency's public website.

The site is static (served by Caddy from ``sitio/``); its form posts JSON to
``/contacto/enviar/`` on the site's own domain, which Caddy forwards here. The
message is emailed to CONTACT_EMAIL (or the platform's superusers) with the
visitor as Reply-To, so answering the email answers the visitor.
"""

import json
import re

from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LIMITS = {"nombre": 120, "email": 200, "interes": 80, "mensaje": 4000}
PER_HOUR = 5


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")) or "?"


def _recipients():
    configured = [e.strip() for e in getattr(settings, "CONTACT_EMAIL", "").split(",") if e.strip()]
    if configured:
        return configured
    from apps.accounts.models import User

    return list(User.objects.filter(is_superuser=True, is_active=True).values_list("email", flat=True))


@csrf_exempt
@require_POST
def contact_submit(request):
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "error": "Formato inválido."}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"ok": False, "error": "Formato inválido."}, status=400)
    # Honeypot: real people never fill the hidden "web" field.
    if str(data.get("web", "")).strip():
        return JsonResponse({"ok": True})

    fields = {k: str(data.get(k, "")).strip()[:n] for k, n in LIMITS.items()}
    if not fields["nombre"] or not fields["mensaje"]:
        return JsonResponse({"ok": False, "error": "Escribe tu nombre y tu mensaje."}, status=400)
    if not EMAIL_RE.match(fields["email"]):
        return JsonResponse({"ok": False, "error": "Revisa tu correo: parece incompleto."}, status=400)

    key = "contacto:" + _client_ip(request)
    count = cache.get(key, 0)
    if count >= PER_HOUR:
        return JsonResponse({"ok": False, "error": "Recibimos varios mensajes seguidos. Escríbenos por WhatsApp."}, status=429)
    cache.set(key, count + 1, 3600)

    to = _recipients()
    if not to:
        return JsonResponse({"ok": False, "error": "No pudimos enviarlo. Escríbenos por WhatsApp."}, status=503)
    body = (
        f"Nuevo mensaje desde la página de Cronopios\n\n"
        f"Nombre: {fields['nombre']}\nCorreo: {fields['email']}\nLe interesa: {fields['interes'] or '-'}\n\n"
        f"{fields['mensaje']}\n\n— Responde este correo para contestarle directamente."
    )
    subject = f"Web Cronopios: {fields['nombre']} ({fields['interes'] or 'contacto'})".replace("\n", " ")
    try:
        EmailMessage(subject=subject, body=body, to=to, reply_to=[fields["email"]]).send()
    except Exception:
        return JsonResponse({"ok": False, "error": "No pudimos enviarlo. Escríbenos por WhatsApp."}, status=503)
    return JsonResponse({"ok": True})
