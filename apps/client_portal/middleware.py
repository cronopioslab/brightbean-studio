"""Cronopios: keep client portal sessions inside the portal, in Spanish."""

from django.shortcuts import redirect
from django.utils import translation

# What a portal session may reach besides the portal itself.
PORTAL_SESSION_ALLOWED_PREFIXES = (
    "/portal/",
    "/static/",
    "/media/",
    "/accounts/logout/",
    "/notifications/unsubscribe/",
    "/health/",
    "/favicon",
)

PORTAL_LANGUAGE = "es"


class PortalSessionMiddleware:
    """A client who came in through a portal link only ever sees the portal.

    Without this, a portal session is a normal login: the client could open the
    team's own pages for their workspace and read pieces still in internal
    review. Portal pages are also rendered in Spanish.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_portal_session = bool(getattr(request, "session", None) and request.session.get("is_portal_session"))
        if is_portal_session and request.user.is_authenticated:
            if not request.path.startswith(PORTAL_SESSION_ALLOWED_PREFIXES):
                return redirect("/portal/")

        if request.path.startswith("/portal/"):
            with translation.override(PORTAL_LANGUAGE):
                request.LANGUAGE_CODE = PORTAL_LANGUAGE
                return self.get_response(request)
        return self.get_response(request)
