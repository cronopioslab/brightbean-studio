"""Cronopios: morning email with what has to be published BY HAND today.

    python manage.py aviso_publicar [--fecha 2026-11-17]

Lists every client-approved piece on a channel that is not connected yet
(the "validación" placeholders), whose date (scheduled, or proposed) falls on
today in that client's timezone: the text ready to copy and links to its
images and videos. Blog channels that forward to someone else are skipped
(that person already got the piece). Sent to the agency owners. Run daily by
the cronopios-aviso timer (see deploy/cronopios-update.sh).
"""

import datetime as dt
from collections import defaultdict
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.composer.models import PlatformPost
from apps.members.models import OrgMembership
from apps.social_accounts.models import SocialAccount


class Command(BaseCommand):
    help = "Envía el aviso de lo que hay que publicar a mano hoy."

    def add_arguments(self, parser):
        parser.add_argument("--fecha", default="", help="AAAA-MM-DD (por defecto, hoy en la zona de cada cliente)")

    def handle(self, *args, **opts):
        app_url = getattr(settings, "APP_URL", "").rstrip("/")
        qs = (
            PlatformPost.objects.filter(
                status="approved",
                social_account__account_platform_id__startswith=SocialAccount.VALIDATION_PLACEHOLDER_PREFIX,
            )
            .select_related("post", "post__workspace", "post__workspace__organization", "social_account")
            .annotate(when=Coalesce("scheduled_at", "post__scheduled_at", "post__proposed_publish_at"))
            .exclude(when__isnull=True)
        )
        by_org = defaultdict(list)
        for pp in qs:
            if "@" in (pp.social_account.account_handle or ""):
                continue  # forwarded to whoever publishes it (blog)
            ws = pp.post.workspace
            tz = ZoneInfo(ws.effective_timezone or "UTC")
            day = dt.date.fromisoformat(opts["fecha"]) if opts["fecha"] else timezone.now().astimezone(tz).date()
            if pp.when.astimezone(tz).date() != day:
                continue
            by_org[ws.organization].append(pp)

        sent = 0
        for org, pps in by_org.items():
            owners = list(
                OrgMembership.objects.filter(organization=org, org_role="owner").values_list("user__email", flat=True)
            )
            if not owners:
                continue
            lines = [f"Hoy toca publicar a mano {len(pps)} pieza{'s' if len(pps) != 1 else ''} ya aprobada{'s' if len(pps) != 1 else ''}.", ""]
            for pp in sorted(pps, key=lambda p: (p.post.workspace.name, p.when)):
                post, ws = pp.post, pp.post.workspace
                tz = ZoneInfo(ws.effective_timezone or "UTC")
                lines += [
                    "=" * 40,
                    f"{ws.name} · {pp.social_account.account_name.replace(' (validación)', '')} · {pp.when.astimezone(tz):%H:%M} ({ws.effective_timezone})",
                    f"Abrir en el panel: {app_url}/workspace/{ws.id}/compose/{post.id}/",
                ]
                media = [pm.media_asset for pm in post.media_attachments.select_related("media_asset").order_by("position")]
                if media:
                    lines.append("Archivos, en orden:")
                    lines += [f"  {i}. {app_url}{a.file.url}" for i, a in enumerate(media, 1) if a.file]
                if post.title:
                    lines += ["", f"Título: {post.title}"]
                lines += ["", "Texto para copiar:", "", (pp.platform_specific_caption or post.caption or "").strip(), ""]
                if post.internal_notes:
                    lines += [f"Notas internas: {post.internal_notes}", ""]
            day_txt = (dt.date.fromisoformat(opts["fecha"]) if opts["fecha"] else timezone.localdate()).strftime("%d/%m")
            EmailMessage(
                subject=f"Hoy se publica a mano ({day_txt}): {len(pps)} pieza{'s' if len(pps) != 1 else ''}",
                body="\n".join(lines),
                to=owners,
            ).send()
            sent += 1
        self.stdout.write(f"Avisos enviados: {sent}.")
