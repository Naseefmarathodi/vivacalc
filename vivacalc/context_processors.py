"""Template context available on every page."""

from __future__ import annotations

from django.conf import settings


def session_limits(request):
    """Expose the session deadline so the page can end it on time.

    Values are advisory — the server enforces the limits regardless.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}

    from vivapanel import session_policy as policy

    end = policy.deadline(request.session)
    return {
        "session_ends_at": int(end.timestamp()) if end else 0,
        "session_idle_seconds": int(policy.idle_timeout().total_seconds()),
        "session_seconds_remaining": policy.seconds_remaining(request.session),
    }


def branding(request):
    """Expose brand constants so templates never hard-code them."""
    return {
        "APP_NAME": settings.APP_NAME,
        "BRAND_NAME": settings.BRAND_NAME,
        "CURRENCY_SYMBOL": settings.CURRENCY_SYMBOL,
    }
