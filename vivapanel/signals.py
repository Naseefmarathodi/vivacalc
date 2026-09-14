"""Authentication signal receivers.

Wired up in VivapanelConfig.ready(). Django sends these regardless of which
view performed the login, so notifications also cover sign-ins through the
Django admin site.
"""

from __future__ import annotations

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from . import notifications
from . import session_policy as policy


@receiver(user_logged_in, dispatch_uid="vivacalc_notify_login")
def on_user_logged_in(sender, request, user, **kwargs):
    if request is not None:
        # Pin the absolute deadline at the moment of sign-in.
        policy.begin(request.session)
    notifications.notify(notifications.LOGIN, user, request)


@receiver(user_logged_out, dispatch_uid="vivacalc_notify_logout")
def on_user_logged_out(sender, request, user, **kwargs):
    # user is None when the session had already gone — nothing to report.
    if user is None:
        return
    reason = policy.REASON_MANUAL
    if request is not None:
        reason = request.session.get(policy.LOGOUT_REASON, policy.REASON_MANUAL)
    notifications.notify(notifications.LOGOUT, user, request, reason=reason)
