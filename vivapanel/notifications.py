"""Sign-in / sign-out notifications: one terminal line, one email.

Three rules govern this module:

1. **Authentication must never break because of mail.** Sending happens on a
   background thread and every failure is caught and logged. If the mail
   server is unreachable or the app password has been revoked, users still
   sign in and out normally.

2. **Authentication must never be slowed by mail.** An SMTP handshake costs
   roughly half a second and can stall far longer, so it never runs inline.

3. **One event produces at most one notification.** Several mechanisms can end
   the same session at nearly the same moment — the timeout middleware, the
   browser-side countdown, and the ``expire_sessions`` sweeper. A short-lived
   cache claim keyed on the session makes the first one win.

The message body is deliberately minimal: username and timestamp only. No IP
address, device, browser or role.
"""

from __future__ import annotations

import logging
import threading

from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger("vivacalc.auth")

#: Plain, greppable terminal lines, e.g.
#:   LOGIN: username=admin | time=2026-09-14 22:30:15
audit = logging.getLogger("vivacalc.audit")

LOGIN = "login"
LOGOUT = "logout"

_LABELS = {LOGIN: "Login", LOGOUT: "Logout"}
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

#: How long a claim blocks a repeat notification for the same session+event.
_DEDUPE_SECONDS = 120


def _recipients(user) -> list[str]:
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


def _claim(event: str, username: str, session_key: str | None) -> bool:
    """Claim this event once. False means someone already reported it.

    Keyed on the session where one exists, so two different sign-ins by the
    same person are both reported, while two mechanisms racing to end the
    *same* session produce a single notification.
    """
    scope = session_key or f"nosession:{timezone.now().timestamp():.3f}"
    key = f"auth-notified:{event}:{username}:{scope}"
    try:
        return bool(cache.add(key, 1, _DEDUPE_SECONDS))
    except Exception:
        # A broken cache must not suppress the notification entirely.
        logger.exception("dedupe claim failed; sending anyway")
        return True


def build_context(event: str, user, when=None, reason: str | None = None) -> dict:
    now = when or timezone.localtime()
    if timezone.is_aware(now):
        now = timezone.localtime(now)
    return {
        "event": event,
        "event_label": _LABELS.get(event, event),
        "username": getattr(user, "username", "unknown"),
        "timestamp_display": now.strftime(_TIME_FORMAT),
        "app_name": settings.APP_NAME,
        "brand_name": settings.BRAND_NAME,
        "reason": reason,
    }


def log_event(event: str, username: str, when=None, reason: str | None = None) -> None:
    """Print the monitoring line. Always runs, even when email is disabled."""
    now = when or timezone.localtime()
    if timezone.is_aware(now):
        now = timezone.localtime(now)
    line = (
        f"{event.upper()}: username={username} "
        f"| time={now.strftime(_TIME_FORMAT)}"
    )
    if reason and reason != "manual":
        line += f" | reason={reason}"
    audit.info(line)


def _deliver(event: str, context: dict, recipients: list[str]) -> None:
    """Render and send. Runs on a background thread; must not raise."""
    try:
        subject = (
            f"[{context['app_name']}] {context['event_label']}: "
            f"{context['username']} at {context['timestamp_display']}"
        )
        message = EmailMultiAlternatives(
            subject=subject,
            body=render_to_string("emails/auth_notification.txt", context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
        )
        message.attach_alternative(
            render_to_string("emails/auth_notification.html", context), "text/html"
        )
        message.send(fail_silently=False)
        logger.info(
            "auth notification sent",
            extra={"event": event, "notified_user": context["username"]},
        )
    except Exception:
        # Deliberately broad: nothing here may surface to the user or affect
        # their session. The log line is the record.
        logger.exception(
            "auth notification failed",
            extra={"event": event, "notified_user": context.get("username")},
        )


def notify(event: str, user, request=None, reason: str | None = None) -> bool:
    """Log the event and queue its email.

    Returns True when an email was dispatched. The terminal line is always
    written first, so monitoring works even with email switched off.
    """
    try:
        if user is None:
            return False

        username = getattr(user, "username", "unknown")
        session_key = None
        if request is not None and hasattr(request, "session"):
            session_key = request.session.session_key

        if not _claim(event, username, session_key):
            logger.debug(
                "duplicate auth event suppressed",
                extra={"event": event, "notified_user": username},
            )
            return False

        when = timezone.localtime()
        log_event(event, username, when, reason)

        if not _should_send(event):
            return False

        recipients = _recipients(user)
        if not recipients:
            logger.warning(
                "auth notification skipped: no recipients configured",
                extra={"event": event},
            )
            return False

        backend = getattr(settings, "EMAIL_BACKEND", "")
        if "smtp" in backend and not getattr(settings, "EMAIL_HOST_PASSWORD", ""):
            logger.error(
                "auth notification skipped: EMAIL_HOST_PASSWORD is not set "
                "while using the SMTP backend - add it to .env",
                extra={"event": event},
            )
            return False

        context = build_context(event, user, when, reason)

        if getattr(settings, "AUTH_NOTIFY_SYNCHRONOUS", False):
            _deliver(event, context, recipients)
            return True

        threading.Thread(
            target=_deliver,
            args=(event, context, recipients),
            name=f"auth-notify-{event}",
            daemon=True,
        ).start()
        return True
    except Exception:
        logger.exception("auth notification dispatch failed", extra={"event": event})
        return False
