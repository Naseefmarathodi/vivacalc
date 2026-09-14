"""Template context available on every page."""

from __future__ import annotations

from django.conf import settings


def branding(request):
    """Expose brand constants so templates never hard-code them."""
    return {
        "APP_NAME": settings.APP_NAME,
        "BRAND_NAME": settings.BRAND_NAME,
        "CURRENCY_SYMBOL": settings.CURRENCY_SYMBOL,
    }
