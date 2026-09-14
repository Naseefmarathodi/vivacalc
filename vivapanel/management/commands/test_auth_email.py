"""Send a test sign-in notification, to prove the mail settings work.

    python manage.py test_auth_email
    python manage.py test_auth_email --event logout --user admin
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from vivapanel import notifications


class Command(BaseCommand):
    help = "Send a test sign-in/sign-out notification email."

    def add_arguments(self, parser):
        parser.add_argument("--event", choices=["login", "logout"], default="login")
        parser.add_argument("--user", help="Username to name in the message.")

    def handle(self, *args, **options):
        User = get_user_model()

        if options["user"]:
            try:
                user = User.objects.get(username=options["user"])
            except User.DoesNotExist as exc:
                raise CommandError(f"No user named {options['user']!r}") from exc
        else:
            user = User.objects.order_by("-is_superuser", "username").first()
            if user is None:
                raise CommandError("No users exist to send a test for.")

        recipients = notifications._recipients(user)

        self.stdout.write("Configuration")
        self.stdout.write(f"  backend      {settings.EMAIL_BACKEND}")
        self.stdout.write(f"  host         {settings.EMAIL_HOST}:{settings.EMAIL_PORT} "
                          f"(TLS={settings.EMAIL_USE_TLS})")
        self.stdout.write(f"  from         {settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write(f"  auth user    {settings.EMAIL_HOST_USER or '(unset)'}")
        password = settings.EMAIL_HOST_PASSWORD
        self.stdout.write(
            f"  password     {'set, ' + str(len(password)) + ' chars' if password else 'NOT SET'}"
        )
        self.stdout.write(f"  enabled      {settings.AUTH_NOTIFY_ENABLED}")
        self.stdout.write(f"  recipients   {', '.join(recipients) or '(none configured)'}")
        self.stdout.write("")

        if "console" in settings.EMAIL_BACKEND:
            self.stdout.write(self.style.WARNING(
                "NOTE: the console backend only PRINTS the message below - "
                "no real email is sent.\n"
                "      Set this in .env to send for real:\n"
                "      EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend\n"
            ))

        if not settings.EMAIL_HOST_PASSWORD and "smtp" in settings.EMAIL_BACKEND:
            self.stderr.write(self.style.ERROR(
                "EMAIL_HOST_PASSWORD is not set — add it to .env and retry."
            ))
            return
        if not recipients:
            self.stderr.write(self.style.ERROR(
                "AUTH_NOTIFY_RECIPIENTS is empty — add it to .env and retry."
            ))
            return

        # Send inline so a failure surfaces here rather than only in the log.
        settings.AUTH_NOTIFY_SYNCHRONOUS = True
        context = notifications.build_context(options["event"], user, None)
        self.stdout.write(f"Sending a {options['event']} notification for "
                          f"{user.username}…")
        try:
            notifications._deliver(options["event"], context, recipients)
        except Exception as exc:  # pragma: no cover - surfaced to the operator
            raise CommandError(f"Send failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(
            f"Done. Check the inbox of: {', '.join(recipients)}"
        ))
