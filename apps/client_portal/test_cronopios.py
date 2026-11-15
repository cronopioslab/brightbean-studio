"""Tests for the Cronopios portal changes: reusable links in every review email,
clients kept inside the portal, Spanish portal, no internal-review notices to
clients, and new posts keeping their images when submitted directly."""

import json

from background_task.models import Task
from django.core import mail
from django.test import Client, RequestFactory, TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals.services import approve_post, submit_for_review
from apps.client_portal.models import MagicLinkToken
from apps.client_portal.services import send_review_email
from apps.client_portal.tasks import TASK_NAME, queue_client_review_email
from apps.composer.services import create_post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.notifications.models import Notification
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


class CronopiosPortalBase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Cronopios")
        self.workspace = Workspace.objects.create(
            organization=self.org, name="Cliente", approval_workflow_mode="required_internal_and_client"
        )
        self.owner = User.objects.create_user(email="owner@example.com", password="x", tos_accepted_at=timezone.now())
        OrgMembership.objects.create(user=self.owner, organization=self.org, org_role="owner")
        WorkspaceMembership.objects.create(user=self.owner, workspace=self.workspace, workspace_role="owner")
        self.client_user = User.objects.create_user(email="client@example.com", password=None)
        WorkspaceMembership.objects.create(user=self.client_user, workspace=self.workspace, workspace_role="client")
        self.account = SocialAccount.objects.create(
            workspace=self.workspace, platform="instagram", account_platform_id="cronopios-validacion-demo", account_name="Instagram demo"
        )

    def _post(self, caption="Pieza"):
        post = create_post(workspace=self.workspace, social_account=self.account, caption=caption, author=self.owner)
        return post[0] if isinstance(post, tuple) else post

    def _to_client(self, post):
        submit_for_review(post, self.owner, self.workspace)
        approve_post(post, self.owner, self.workspace)
        post.refresh_from_db()
        return post

    def _queued(self):
        return Task.objects.filter(task_name=TASK_NAME)


class ReviewEmailTests(CronopiosPortalBase):
    def test_internal_submit_does_not_notify_the_client(self):
        submit_for_review(self._post(), self.owner, self.workspace)
        self.assertFalse(Notification.objects.filter(user=self.client_user).exists())
        self.assertFalse(self._queued().exists())

    def test_a_burst_of_approvals_queues_one_email(self):
        self._to_client(self._post("Uno"))
        self._to_client(self._post("Dos"))
        self.assertEqual(self._queued().count(), 1)
        params = json.loads(self._queued().get().task_params)
        self.assertEqual(params[0], [str(self.workspace.id), str(self.client_user.id)])

    def test_email_is_spanish_counts_pieces_and_carries_the_link(self):
        self._to_client(self._post("Uno"))
        self._to_client(self._post("Dos"))
        mail.outbox.clear()
        self.assertTrue(send_review_email(self.workspace, self.client_user))
        msg = mail.outbox[-1]
        token = MagicLinkToken.objects.get(user=self.client_user, workspace=self.workspace)
        self.assertIn("2 piezas para revisar", msg.subject)
        self.assertIn(f"/portal/{token.token}/", msg.body)

    def test_later_emails_reuse_the_same_link(self):
        self._to_client(self._post())
        send_review_email(self.workspace, self.client_user)
        send_review_email(self.workspace, self.client_user, reminder=True)
        tokens = MagicLinkToken.objects.filter(user=self.client_user, workspace=self.workspace, expires_at__gt=timezone.now())
        self.assertEqual(tokens.count(), 1)
        self.assertIn("Recordatorio", mail.outbox[-1].subject)

    def test_nothing_is_sent_when_nothing_is_pending(self):
        self.assertFalse(send_review_email(self.workspace, self.client_user))
        self.assertFalse(MagicLinkToken.objects.exists())

    def test_queue_skips_a_duplicate(self):
        queue_client_review_email(self.workspace, self.client_user)
        queue_client_review_email(self.workspace, self.client_user)
        self.assertEqual(self._queued().count(), 1)


class PortalSessionTests(CronopiosPortalBase):
    def _portal_client(self):
        token = MagicLinkToken.objects.create(user=self.client_user, workspace=self.workspace)
        browser = Client()
        browser.post(f"/portal/{token.token}/")
        return browser

    def test_portal_session_cannot_open_team_pages(self):
        browser = self._portal_client()
        for path in (
            f"/workspace/{self.workspace.id}/calendar/",
            f"/workspace/{self.workspace.id}/compose/",
            "/settings/",
        ):
            response = browser.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertEqual(response["Location"], "/portal/", path)

    def test_portal_session_skips_the_app_terms_and_is_in_spanish(self):
        browser = self._portal_client()
        response = browser.get("/portal/approvals/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Piezas para revisar")

    def test_team_login_is_not_redirected(self):
        browser = Client()
        browser.force_login(self.owner)
        response = browser.get(f"/workspace/{self.workspace.id}/calendar/")
        self.assertNotEqual(response.get("Location"), "/portal/")


class PendingMediaTests(CronopiosPortalBase):
    def test_helper_attaches_session_media_to_the_post(self):
        from django.contrib.sessions.backends.db import SessionStore

        from apps.composer.views import _attach_pending_session_media
        from apps.media_library.models import MediaAsset

        asset = MediaAsset.objects.create(
            organization=self.org, workspace=self.workspace, uploaded_by=self.owner,
            filename="a.jpg", media_type="image", mime_type="image/jpeg", file_size=1, file="media_library/a.jpg",
        )
        request = RequestFactory().post("/")
        request.session = SessionStore()
        request.session[f"pending_media_{self.workspace.id}"] = [str(asset.id)]
        post = self._post()
        _attach_pending_session_media(request, post, self.workspace)
        self.assertEqual(post.media_attachments.count(), 1)
        self.assertNotIn(f"pending_media_{self.workspace.id}", request.session)


class PlaceholderAccountTests(CronopiosPortalBase):
    def test_health_check_leaves_a_tokenless_placeholder_alone(self):
        from apps.social_accounts.tasks import _check_social_account_health

        _check_social_account_health(str(self.account.id))
        self.account.refresh_from_db()
        self.assertEqual(self.account.connection_status, SocialAccount.ConnectionStatus.CONNECTED)
        self.assertIsNone(self.account.last_health_check_at)

    def test_creating_a_placeholder_queues_no_analytics_backfill(self):
        SocialAccount.objects.create(
            workspace=self.workspace, platform="facebook",
            account_platform_id=SocialAccount.VALIDATION_PLACEHOLDER_PREFIX + "fb",
            account_name="Facebook demo", connection_status="connected",
        )
        self.assertFalse(Task.objects.filter(task_name__contains="backfill_account_analytics").exists())


class AgregarClienteCommandTests(CronopiosPortalBase):
    def test_adds_a_portal_client_with_a_placeholder_account(self):
        from django.core.management import call_command

        call_command(
            "agregar_cliente", espacio="Nuevo", email="Persona@Cliente.com", nombre="Persona", organizacion="Cronopios"
        )
        ws = Workspace.objects.get(name="Nuevo")
        self.assertEqual(ws.approval_workflow_mode, "required_internal_and_client")
        user = User.objects.get(email="persona@cliente.com")
        self.assertTrue(WorkspaceMembership.objects.filter(user=user, workspace=ws, workspace_role="client").exists())
        self.assertFalse(user.has_usable_password())
        self.assertTrue(SocialAccount.objects.get(workspace=ws).is_validation_placeholder)
        self.assertTrue(WorkspaceMembership.objects.filter(user=self.owner, workspace=ws, workspace_role="owner").exists())
        # No empty organization of their own.
        self.assertEqual(list(OrgMembership.objects.filter(user=user).values_list("organization__name", flat=True)), ["Cronopios"])

    def test_refuses_to_turn_a_team_member_into_a_client(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("agregar_cliente", espacio=self.workspace.name, email=self.owner.email, organizacion="Cronopios")


class ForwardApprovedPieceTests(CronopiosPortalBase):
    def _blog(self, email="editor@cliente.com"):
        return SocialAccount.objects.create(
            workspace=self.workspace, platform="devto",
            account_platform_id=SocialAccount.VALIDATION_PLACEHOLDER_PREFIX + "blog",
            account_name="Blog (validación)", account_handle=email, connection_status="connected",
        )

    def _blog_post(self, account):
        post = create_post(workspace=self.workspace, social_account=account, caption="Texto del artículo", title="Mi artículo", author=self.owner)
        return post[0] if isinstance(post, tuple) else post

    def _client_approves(self, post):
        from apps.approvals.services import approve_post

        self._to_client(post)
        approve_post(post, self.client_user, self.workspace)

    def _forwards(self):
        return Task.objects.filter(task_name="apps.client_portal.tasks.forward_approved_piece")

    def test_client_approval_queues_the_forward_and_email_reaches_the_editor(self):
        from apps.client_portal.tasks import forward_approved_piece

        post = self._blog_post(self._blog())
        self._to_client(post)
        self.assertFalse(self._forwards().exists())  # internal approval alone does not forward
        from apps.approvals.services import approve_post

        approve_post(post, self.client_user, self.workspace)
        self.assertEqual(self._forwards().count(), 1)
        mail.outbox.clear()
        forward_approved_piece.now(str(post.platform_posts.get().id), str(self.client_user.id))
        msg = mail.outbox[-1]
        self.assertEqual(msg.to, ["editor@cliente.com"])
        self.assertIn(self.owner.email, msg.cc)
        self.assertIn("Mi artículo", msg.subject)
        self.assertIn("Texto del artículo", msg.body)

    def test_placeholder_without_email_is_not_forwarded(self):
        post = self._blog_post(self._blog(email=""))
        self._client_approves(post)
        self.assertFalse(self._forwards().exists())


class AsegurarCanalesTests(CronopiosPortalBase):
    def test_creates_the_three_channels_once(self):
        from django.core.management import call_command

        call_command("asegurar_canales")
        call_command("asegurar_canales")
        platforms = sorted(
            SocialAccount.objects.filter(workspace=self.workspace)
            .exclude(account_platform_id="cronopios-validacion-demo")
            .values_list("platform", flat=True)
        )
        self.assertEqual(platforms, ["devto", "instagram", "linkedin_company"])


class AgregarClienteZonaTests(CronopiosPortalBase):
    def test_sets_the_client_timezone_and_rejects_unknown_ones(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        call_command("agregar_cliente", espacio="Zona", email="z@cliente.com", zona="Europe/Madrid", organizacion="Cronopios")
        self.assertEqual(Workspace.objects.get(name="Zona").timezone, "Europe/Madrid")
        with self.assertRaises(CommandError):
            call_command("agregar_cliente", espacio="Zona", email="z@cliente.com", zona="Marte/Base", organizacion="Cronopios")
