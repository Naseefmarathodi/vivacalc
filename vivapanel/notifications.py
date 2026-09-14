"""Sign-in / sign-out email notifications.

Two rules govern this module:

1. **Mail must never break authentication.** Sending happens on a background
   thread and every failure is caught and logged. If Gmail is unreachable, the
   mailbox is full, or the app password has been revoked, users still sign in
   and out normally — they just don't get an email. Authentication is the
   product; notification is a side effect.

2. **Mail must never slow authentication.** An SMTP handshake to Gmail costs
   roughly half a second and can stall far longer. Doing that inline would put
   it directly in the login request path, so it is handed to a thread and the
   response returns immediately.

A thread (rather than Celery) is the right size of tool here: this app has a
handful of staff, so the volume is a few messages a day, and a task queue would
be more infrastructure than the problem justifies.
"""

from __future__ import annotations

import logging
import threading

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger("vivacalc.auth")

LOGIN = "login"
LOGOUT = "logout"

_EVENT_LABELS = {LOGIN: "Signed in", LOGOUT: "Signed out"}


def client_ip(request) -> str:
    """Best-effort client address, mirroring the login throttle's logic."""
    if request is None:
        return "unknown"
    if getattr(settings, "SECURE_PROXY_SSL_HEADER", None):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def _recipients(user) -> list[str]:
    """Who receives this notification, de-duplicated and order-preserving."""
    people = list(getattr(settings, "AUTH_NOTIFY_RECIPIENTS", []))
    if getattr(settings, "AUTH_NOTIFY_USER_TOO", False):
        address = (getattr(user, "email", "") or "").strip()
        if address:
            people.append(address)
    seen, unique = set(), []
    for address in people:
        key = address.lower()
        if key not in seen:
            seen.add(key)
            unique.append(address)
    return unique


def _should_send(event: str) -> bool:
    if not getattr(settings, "AUTH_NOTIFY_ENABLED", False):
        return False
    if event == LOGIN:
        return getattr(settings, "AUTH_NOTIFY_ON_LOGIN", False)
    if event == LOGOUT:
        return getattr(settings, "AUTH_NOTIFY_ON_LOGOUT", False)
    return False


def build_context(event: str, user, request) -> dict:
    now = timezone.localtime()
    return {
        "event": event,
        "event_label": _EVENT_LABELS.get(event, event),
        "username": getattr(user, "username", "unknown"),
        "display_name": getattr(user, "display_name", None)
        or getattr(user, "username", "unknown"),
        "email": getattr(user, "email", "") or "—",
        "role": "Administrator"
        if getattr(user, "is_panel_admin", False)
        else "Staff",
        "timestamp": now,
        "timestamp_display": now.strftime("%d %b %Y at %H:%M:%S %Z"),
        "ip_address": client_ip(request),
        "user_agent": (
            request.META.get("HTTP_USER_AGENT", "") if request is not None else ""
        )[:300]
        or "—",
        "app_name": settings.APP_NAME,
        "brand_name": settings.BRAND_NAME,
    }


def _deliver(event: str, context: dict, recipients: list[str]) -> None:
    """Render and send. Runs on a background thread; must not raise."""
    try:
        subject = (
            f"[{context['app_name']}] {context['event_label']}: "
            f"{context['username']} — {context['timestamp_display']}"
        )
        text_body = render_to_string("emails/auth_notification.txt", context)
        html_body = render_to_string("emails/auth_notification.html", context)

        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
        )
        message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=False)

        logger.info(
            "auth notification sent",
            extra={
                "event": event,
                "notified_user": context["username"],
                "recipient_count": len(recipients),
            },
        )
    except Exception:
        # Deliberately broad: nothing that happens here may surface to the user
        # or affect their session. The log line is the record.
        logger.exception(
            "auth notification failed",
            extra={"event": event, "notified_user": context.get("username")},
        )


def notify(event: str, user, request=None) -> bool:
    """Queue a sign-in/sign-out notification.

    Returns True when a send was dispatched, False when it was skipped
    (disabled, no recipients, or no user). Never raises.
    """
    try:
        if user is None or not _should_send(event):
            return False

        recipients = _recipients(user)
        if not recipients:
            logger.warning(
                "auth notification skipped: no recipients configured",
                extra={"event": event},
            )
            return False

        # A console/file backend needs no credentials; an SMTP one without a
        # password will always fail, so say so once, clearly, rather than
        # logging an SMTPAuthenticationError on every single sign-in.
        backend = getattr(settings, "EMAIL_BACKEND", "")
        if "smtp" in backend and not getattr(settings, "EMAIL_HOST_PASSWORD", ""):
            logger.error(
                "auth notification skipped: EMAIL_HOST_PASSWORD is not set "
                "while using the SMTP backend - add it to .env",
                extra={"event": event},
            )
            return False

        context = build_context(event, user, request)

        if getattr(settings, "AUTH_NOTIFY_SYNCHRONOUS", False):
            # Used by the test suite and the check command, so assertions can
            # inspect mail.outbox without racing a thread.
            _deliver(event, context, recipients)
            return True

        thread = threading.Thread(
            target=_deliver,
            args=(event, context, recipients),
            name=f"auth-notify-{event}",
            daemon=True,
        )
        thread.start()
        return True
    except Exception:
        logger.exception("auth notification dispatch failed", extra={"event": event})
        return False
