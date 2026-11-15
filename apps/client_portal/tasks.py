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
