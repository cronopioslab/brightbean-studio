"""Cronopios: make sure every client workspace has its approval-only channels.

    python manage.py asegurar_canales

For each workspace that runs internal + client approval, creates (if missing)
placeholder channels for Instagram, LinkedIn and the blog. They never publish;
they let pieces be drafted and approved before the real channel is connected.
To have approved blog pieces emailed to whoever publishes the blog, put that
person's email in the blog channel's "account handle" (Django admin).
Safe to run any number of times.
"""

from django.core.management.base import BaseCommand

from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace

CHANNELS = (
    ("instagram", "instagram", "Instagram (validación)"),
    ("linkedin_company", "linkedin", "LinkedIn (validación)"),
    ("devto", "blog", "Blog (validación)"),
)


class Command(BaseCommand):
    help = "Crea los canales de validación (Instagram, LinkedIn, Blog) en cada cliente."

    def handle(self, *args, **opts):
        # A workspace with a portal client always waits for that client.
        fixed = (
            Workspace.objects.filter(memberships__workspace_role="client", is_archived=False)
            .exclude(approval_workflow_mode="required_internal_and_client")
            .distinct()
        )
        for ws in fixed:
            ws.approval_workflow_mode = "required_internal_and_client"
            ws.save(update_fields=["approval_workflow_mode"])
            self.stdout.write(f"{ws.name}: aprobación del cliente activada.")
        created = 0
        for ws in Workspace.objects.filter(approval_workflow_mode="required_internal_and_client", is_archived=False):
            for platform, slug, name in CHANNELS:
                _, made = SocialAccount.objects.get_or_create(
                    workspace=ws,
                    platform=platform,
                    account_platform_id=SocialAccount.VALIDATION_PLACEHOLDER_PREFIX + slug,
                    defaults={"account_name": name, "connection_status": "connected"},
                )
                if made:
                    created += 1
                    self.stdout.write(f"{ws.name}: canal «{name}» creado.")
        self.stdout.write(f"Listo. Canales nuevos: {created}.")
