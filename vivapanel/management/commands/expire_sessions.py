"""Close out sessions that expired while nobody was using the browser.

The middleware ends a session on the user's *next request*. That is what
actually enforces the limit — an expired session is refused even if the tab
stayed open. But if someone simply walks away, no request arrives, so no
logout is reported until they come back.

This command closes that reporting gap: it finds sessions past their deadline,
emits the LOGOUT line and email for each, and deletes the rows.

Run it on a schedule — every 5 minutes is plenty:

    Linux/macOS  */5 * * * * cd /path && venv/bin/python manage.py expire_sessions
    Windows      schtasks /create /tn "VivaCalc sessions" ^
                   /tr "C:\\apps\\vivacalc\\venv\\Scripts\\python.exe C:\\apps\\vivacalc\\manage.py expire_sessions" ^
                   /sc minute /mo 5

The de-duplication in notifications.notify() means a user who returns at the
same moment the sweeper runs still produces only one logout notification.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.utils import timezone

from vivapanel import notifications
from vivapanel import session_policy as policy


class Command(BaseCommand):
    help = "Report and delete sessions that have passed their expiry."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show what would happen without sending or deleting.",
        )
        parser.add_argument(
            "--quiet", action="store_true", help="Only report problems.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        quiet = options["quiet"]
        now = timezone.now()
        User = get_user_model()

        reported = deleted = 0

        for session in Session.objects.all().iterator():
            try:
                data = session.get_decoded()
            except Exception:
                # Undecodable (e.g. rotated SECRET_KEY) — it can never be used
                # again, so remove it.
                if not dry_run:
                    session.delete()
                    deleted += 1
                continue

            past_cookie_expiry = session.expire_date <= now
            reason = policy.expiry_reason(data, now)

            if not past_cookie_expiry and reason is None:
                continue

            reason = reason or policy.REASON_EXPIRED
            user_id = data.get("_auth_user_id")
            user = User.objects.filter(pk=user_id).first() if user_id else None

            if user is not None:
                if dry_run:
                    self.stdout.write(
                        f"  would report {reason}: {user.username} "
                        f"(session {session.session_key[:8]}…)"
                    )
                else:
                    # A fake request carrying only the session key, so the
                    # de-duplication claim is scoped to this session.
                    sent = notifications.notify(
                        notifications.LOGOUT,
                        user,
                        _SessionKeyOnly(session.session_key),
                        reason=reason,
                    )
                    if sent is not None:
                        reported += 1

            if not dry_run:
                session.delete()
                deleted += 1

        if not quiet:
            verb = "would delete" if dry_run else "deleted"
            self.stdout.write(
                f"{verb} {deleted} expired session(s); reported {reported}"
            )


class _SessionKeyOnly:
    """Minimal stand-in so notify() can scope its de-duplication claim."""

    def __init__(self, session_key: str):
        self.session = _Session(session_key)


class _Session:
    def __init__(self, session_key: str):
        self.session_key = session_key
