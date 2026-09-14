"""Authentication signal receivers.

Wired up in VivapanelConfig.ready(). Django sends these regardless of which
view performed the login, so notifications also cover sign-ins through the
Django admin site.
"""

from __future__ import annotations

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from . import notifications


@receiver(user_logged_in, dispatch_uid="vivacalc_notify_login")
def on_user_logged_in(sender, request, user, **kwargs):
    notifications.notify(notifications.LOGIN, user, request)


@receiver(user_logged_out, dispatch_uid="vivacalc_notify_logout")
def on_user_logged_out(sender, request, user, **kwargs):
    # user is None when the session had already expired — nothing to report.
    if user is not None:
        notifications.notify(notifications.LOGOUT, user, request)
