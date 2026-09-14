"""Server-side session expiry enforcement.

This is the authoritative mechanism. The browser-side countdown in app.js only
makes the logout *prompt*; it cannot keep a session alive, and removing it
changes nothing about when access actually ends.
"""

from __future__ import annotations

import logging

from django.contrib.auth import logout as auth_logout
from django.utils import timezone

from . import session_policy as policy

logger = logging.getLogger("vivacalc.auth")


class SessionTimeoutMiddleware:
    """End sessions that have hit the absolute cap or the idle timeout.

    Runs on every authenticated request, so a user cannot keep access by
    leaving a tab open: the very next request they make is rejected and the
    session row is destroyed server-side.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)

        if user is not None and user.is_authenticated:
            now = timezone.now()
            reason = policy.expiry_reason(request.session, now)

            if reason is not None:
                # Stash the reason before logout() flushes the session, so the
                # user_logged_out receiver can report why it ended.
                request.session[policy.LOGOUT_REASON] = reason
                # logout() flushes the session server-side and clears the
                # cookie; the session key is gone, not merely marked expired.
                auth_logout(request)
            else:
                policy.touch(request.session, now)

        return self.get_response(request)
