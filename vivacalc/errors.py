"""Error views.

Rendered instead of Django's default pages so a production failure still shows
the Viva brand and a route back, and never a traceback.
"""

from __future__ import annotations

import logging

from django.shortcuts import render

logger = logging.getLogger("vivacalc.errors")


def permission_denied(request, exception=None):
    return render(
        request,
        "errors/error.html",
        {
            "status_code": 403,
            "title": "You don't have access to this page",
            "message": "Your account doesn't have permission to view this area. "
                       "If you think that's wrong, ask an administrator to check "
                       "your role.",
        },
        status=403,
    )


def page_not_found(request, exception=None):
    return render(
        request,
        "errors/error.html",
        {
            "status_code": 404,
            "title": "Page not found",
            "message": "The page you're looking for doesn't exist, or it may "
                       "have been moved.",
        },
        status=404,
    )


def server_error(request):
    logger.error("unhandled server error", extra={"path": request.path})
    return render(
        request,
        "errors/error.html",
        {
            "status_code": 500,
            "title": "Something went wrong",
            "message": "We hit an unexpected error and it has been logged. "
                       "Please try again — if it keeps happening, contact your "
                       "administrator.",
        },
        status=500,
    )
