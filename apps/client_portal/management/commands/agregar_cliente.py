"""Cronopios: add a client who approves through the portal, with no account.

    python manage.py agregar_cliente --espacio "Initium" --email persona@cliente.com [--nombre "Nombre"] [--enviar-enlace]

Creates the client workspace if it does not exist (two-stage approval, plus an
Instagram placeholder so pieces can be created before the real channel is
connected), then adds the person with the client role. The invitation flow is
not used: it asks the client to create an account, which this setup closes.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Agrega un cliente que aprueba desde el portal, sin cuenta."

    def add_arguments(self, parser):
        parser.add_argument("--espacio", required=True, help="Nombre del espacio del cliente, p. ej. Initium")
        parser.add_argument("--email", required=True, help="Correo de la persona que aprueba")
        parser.add_argument("--nombre", default="", help="Nombre de la persona (para el saludo del correo)")
        parser.add_argument("--organizacion", default="", help="Organización; por defecto, la única que exista")
        parser.add_argument("--zona", default="", help="Zona horaria del cliente, p. ej. Europe/Madrid")
        parser.add_argument("--enviar-enlace", action="store_true", help="Enviar ya el correo con su enlace")

    def handle(self, *args, **opts):
        orgs = Organization.objects.filter(deleted_at__isnull=True)
        if opts["organizacion"]:
            orgs = orgs.filter(name=opts["organizacion"])
        else:
            # The agency's organization: the one owned by an administrator.
            orgs = orgs.filter(memberships__org_role="owner", memberships__user__is_superuser=True).distinct()
        if orgs.count() != 1:
            raise CommandError("No encuentro una única organización; usa --organizacion.")
        org = orgs.get()
        if opts["zona"]:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            try:
                ZoneInfo(opts["zona"])
            except (ZoneInfoNotFoundError, ValueError):
                raise CommandError(f"No conozco la zona horaria «{opts['zona']}»; usa, p. ej., Europe/Madrid.")
        owner = OrgMembership.objects.filter(organization=org, org_role="owner").select_related("user").first()

        with transaction.atomic():
            ws, created = Workspace.objects.get_or_create(
                organization=org,
                name=opts["espacio"],
                defaults={"approval_workflow_mode": "required_internal_and_client"},
            )
            if created and owner:
                WorkspaceMembership.objects.get_or_create(
                    user=owner.user, workspace=ws, defaults={"workspace_role": "owner"}
                )
            if opts["zona"] and ws.timezone != opts["zona"]:
                ws.timezone = opts["zona"]
                ws.save(update_fields=["timezone"])
            SocialAccount.objects.get_or_create(
                workspace=ws,
                platform="instagram",
                account_platform_id=SocialAccount.VALIDATION_PLACEHOLDER_PREFIX + "instagram",
                defaults={"account_name": "Instagram (validación)", "connection_status": "connected"},
            )

            email = opts["email"].strip().lower()
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                user = User(email=email)
                user.set_unusable_password()
                user._skip_provisioning = True
                user.save()
            if opts["nombre"] and not user.name:
                user.name = opts["nombre"]
            user.tos_accepted_at = user.tos_accepted_at or timezone.now()
            user.save()
            OrgMembership.objects.get_or_create(user=user, organization=org, defaults={"org_role": "member"})
            membership, _ = WorkspaceMembership.objects.get_or_create(
                user=user, workspace=ws, defaults={"workspace_role": "client"}
            )
            if membership.workspace_role != "client":
                raise CommandError(f"{email} ya es parte del equipo de {ws.name}; no lo convierto en cliente.")

        self.stdout.write(f"Listo: {email} aprueba las piezas de «{ws.name}» desde el portal.")
        if opts["enviar_enlace"]:
            from apps.client_portal.services import generate_magic_link

            generate_magic_link(ws, user, created_by=owner.user if owner else user)
            self.stdout.write("Le envié el correo con su enlace.")
        else:
            self.stdout.write("Le llega el enlace con el primer aviso de piezas para revisar.")
