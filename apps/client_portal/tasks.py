"""Cronopios: client review emails, sent after a short delay so a burst of
approvals reaches the client as one email instead of one per piece."""

import json
import logging

from background_task import background

logger = logging.getLogger(__name__)

REVIEW_EMAIL_DELAY_SECONDS = 120
TASK_NAME = "apps.client_portal.tasks.send_client_review_email"


@background(schedule=REVIEW_EMAIL_DELAY_SECONDS)
def send_client_review_email(workspace_id, user_id, reminder=False):
    from django.contrib.auth import get_user_model

    from apps.workspaces.models import Workspace

    from .services import send_review_email

    workspace = Workspace.objects.filter(id=workspace_id).first()
    user = get_user_model().objects.filter(id=user_id).first()
    if workspace is None or user is None:
        return
    send_review_email(workspace, user, reminder=reminder)


def queue_client_review_email(workspace, client_user, *, reminder=False):
    """Queue one review email for this client unless one is already waiting."""
    from background_task.models import Task

    params = json.dumps([[str(workspace.id), str(client_user.id)], {"reminder": reminder}])
    if Task.objects.filter(task_name=TASK_NAME, task_params=params, failed_at__isnull=True).exists():
        return
    send_client_review_email(str(workspace.id), str(client_user.id), reminder=reminder)


# ---------------------------------------------------------------------------
# Cronopios: approved pieces for a channel someone else publishes (a client's
# blog) are emailed to that person once the client signs off.
# ---------------------------------------------------------------------------

FORWARD_ATTACH_LIMIT_BYTES = 15 * 1024 * 1024


@background(schedule=5)
def forward_approved_piece(platform_post_id, approver_id):
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    from zoneinfo import ZoneInfo

    from django.utils import timezone

    from apps.common.mail import send_or_raise, transactional
    from apps.composer.models import PlatformPost
    from apps.members.models import OrgMembership

    pp = (
        PlatformPost.objects.select_related("post", "post__workspace", "post__workspace__organization", "social_account")
        .filter(id=platform_post_id)
        .first()
    )
    if pp is None:
        return
    account = pp.social_account
    to = (account.account_handle or "").strip()
    if "@" not in to:
        return
    post = pp.post
    workspace = post.workspace
    approver = get_user_model().objects.filter(id=approver_id).first()
    owners = list(
        OrgMembership.objects.filter(organization=workspace.organization, org_role="owner").values_list(
            "user__email", flat=True
        )
    )

    title = (pp.platform_specific_title or post.title or "").strip()
    body = (pp.platform_specific_caption or post.caption or "").strip()
    when = pp.scheduled_at or post.scheduled_at or post.proposed_publish_at
    tz = workspace.effective_timezone or "UTC"
    app_url = getattr(settings, "APP_URL", "").rstrip("/")

    media = []
    attach_total = 0
    for pm in post.media_attachments.select_related("media_asset").order_by("position"):
        asset = pm.media_asset
        if not asset.file:
            continue
        media.append({"name": asset.filename or asset.file.name.rsplit("/", 1)[-1], "url": app_url + asset.file.url, "asset": asset})
        attach_total += asset.file_size or 0

    context = {
        "workspace": workspace,
        "channel": account.account_name,
        "title": title,
        "body": body,
        "when": timezone.localtime(when, ZoneInfo(tz)) if when else None,
        "tz": tz,
        "approver": approver,
        "media": media,
        "attached": attach_total <= FORWARD_ATTACH_LIMIT_BYTES,
    }
    subject = f"{workspace.name} · Aprobado para publicar: {title or post.caption_snippet}"
    msg = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string("client_portal/email/approved_forward.txt", context),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@localhost"),
        to=[to],
        cc=[e for e in owners if e and e.lower() != to.lower()],
        reply_to=owners[:1] or None,
        headers=transactional(),
    )
    if context["attached"]:
        for m in media:
            try:
                with m["asset"].file.open("rb") as fh:
                    msg.attach(m["name"], fh.read(), m["asset"].mime_type or None)
            except Exception:
                logger.exception("Could not attach %s to the forward of %s", m["name"], platform_post_id)
    try:
        send_or_raise(msg)
    except Exception:
        logger.exception("Could not forward approved piece %s to %s", platform_post_id, to)
        raise
