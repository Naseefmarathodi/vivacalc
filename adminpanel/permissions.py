"""Authorisation helpers.

One definition of "may use the admin panel", used by every protected view, so
the rule cannot drift between them.
"""

from __future__ import annotations

from functools import wraps
from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


def is_panel_admin(user) -> bool:
    """True when *user* may use the admin panel."""
    return bool(
        user and user.is_authenticated and getattr(user, "is_panel_admin", False)
    )


def panel_admin_required(view_func):
    """Gate a view behind panel-admin access.

    The two failure cases are deliberately different:

    * not signed in  -> the login page, with ``next`` preserved, because the
      honest problem is a missing session (a session timeout must not read as
      "you are forbidden");
    * signed in as staff -> the access-denied page with a real 403, because
      signing in again would not help.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if is_panel_admin(request.user):
            return view_func(request, *args, **kwargs)
        if not request.user.is_authenticated:
            login_url = reverse(settings.LOGIN_URL)
            return redirect(f"{login_url}?{urlencode({'next': request.get_full_path()})}")
        return redirect("adminpanel:permission_denied_page")

    return _wrapped
