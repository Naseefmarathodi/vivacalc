"""Sign-in / sign-out email notifications.

The load-bearing tests here are the failure ones: authentication must keep
working when mail does not.
"""

from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from vivapanel import notifications

from .factories import PASSWORD, make_admin, make_staff

RECIPIENTS = ["ops@example.com", "manager@example.com"]

NOTIFY = dict(
    AUTH_NOTIFY_ENABLED=True,
    AUTH_NOTIFY_RECIPIENTS=RECIPIENTS,
    AUTH_NOTIFY_ON_LOGIN=True,
    AUTH_NOTIFY_ON_LOGOUT=True,
    AUTH_NOTIFY_USER_TOO=False,
    # Send inline so assertions don't race the background thread.
    AUTH_NOTIFY_SYNCHRONOUS=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)


@override_settings(**NOTIFY)
class LoginNotificationTests(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox = []
        self.staff = make_staff("rahul")

    def test_signing_in_sends_one_email_to_every_recipient(self):
        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.staff.username, "password": PASSWORD},
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertCountEqual(mail.outbox[0].to, RECIPIENTS)

    def test_the_subject_names_the_user_and_the_event(self):
        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.staff.username, "password": PASSWORD},
        )
        subject = mail.outbox[0].subject
        self.assertIn("Login", subject)
        self.assertIn("rahul", subject)

    def test_the_body_carries_only_the_username_and_time(self):
        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.staff.username, "password": PASSWORD},
        )
        body = mail.outbox[0].body
        self.assertIn("rahul", body)
        self.assertRegex(body, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
        # Everything else was deliberately removed.
        for absent in ("IP address", "Device", "Staff", "Role", "Mozilla"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, body)

    def test_an_html_alternative_is_attached(self):
        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.staff.username, "password": PASSWORD},
        )
        alternatives = mail.outbox[0].alternatives
        self.assertEqual(len(alternatives), 1)
        self.assertEqual(alternatives[0].mimetype, "text/html")
        self.assertIn("Login", alternatives[0].content)

    def test_an_admins_role_is_not_disclosed(self):
        """Role was removed from the message along with IP and device."""
        admin = make_admin("boss")
        self.client.post(
            reverse("vivacalc:login"),
            {"username": admin.username, "password": PASSWORD},
        )
        self.assertIn("boss", mail.outbox[0].body)
        self.assertNotIn("Administrator", mail.outbox[0].body)

    def test_a_failed_sign_in_sends_nothing(self):
        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.staff.username, "password": "wrong-password"},
        )
        self.assertEqual(mail.outbox, [])


@override_settings(**NOTIFY)
class LogoutNotificationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = make_staff("rahul")
        self.client.force_login(self.staff)
        mail.outbox = []

    def test_signing_out_sends_a_notification(self):
        self.client.post(reverse("vivacalc:logout"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Logout", mail.outbox[0].subject)
        self.assertCountEqual(mail.outbox[0].to, RECIPIENTS)

    def test_a_get_to_logout_sends_nothing(self):
        """GET only shows the confirmation page; no session ends."""
        self.client.get(reverse("vivacalc:logout"))
        self.assertEqual(mail.outbox, [])


@override_settings(**NOTIFY)
class AuthenticationSurvivesMailFailureTests(TestCase):
    """The most important tests in this file."""

    def setUp(self):
        cache.clear()
        self.staff = make_staff("rahul")
        mail.outbox = []

    def test_sign_in_succeeds_when_the_mail_server_is_unreachable(self):
        with patch(
            "django.core.mail.EmailMultiAlternatives.send",
            side_effect=OSError("Connection refused"),
        ):
            response = self.client.post(
                reverse("vivacalc:login"),
                {"username": self.staff.username, "password": PASSWORD},
                follow=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["user"].is_authenticated)
        # And the session really works on the next request.
        self.assertEqual(
            self.client.get(reverse("vivacalc:dashboard")).status_code, 200
        )

    def test_sign_out_succeeds_when_the_mail_server_is_unreachable(self):
        self.client.force_login(self.staff)
        with patch(
            "django.core.mail.EmailMultiAlternatives.send",
            side_effect=OSError("Connection refused"),
        ):
            response = self.client.post(reverse("vivacalc:logout"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.get(reverse("vivacalc:dashboard")).status_code, 302
        )

    def test_sign_in_succeeds_when_authentication_to_gmail_is_rejected(self):
        """e.g. the app password was revoked."""
        import smtplib

        with patch(
            "django.core.mail.EmailMultiAlternatives.send",
            side_effect=smtplib.SMTPAuthenticationError(535, b"Bad credentials"),
        ):
            response = self.client.post(
                reverse("vivacalc:login"),
                {"username": self.staff.username, "password": PASSWORD},
                follow=True,
            )
        self.assertTrue(response.context["user"].is_authenticated)

    def test_sign_in_succeeds_when_the_template_is_broken(self):
        with patch(
            "vivapanel.notifications.render_to_string",
            side_effect=Exception("template exploded"),
        ):
            response = self.client.post(
                reverse("vivacalc:login"),
                {"username": self.staff.username, "password": PASSWORD},
                follow=True,
            )
        self.assertTrue(response.context["user"].is_authenticated)

    def test_notify_never_raises(self):
        with patch(
            "vivapanel.notifications.build_context",
            side_effect=Exception("boom"),
        ):
            self.assertFalse(
                notifications.notify(notifications.LOGIN, self.staff, None)
            )


class NotificationConfigurationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = make_staff("rahul", email="rahul@example.com")
        mail.outbox = []

    @override_settings(**{**NOTIFY, "AUTH_NOTIFY_ENABLED": False})
    def test_disabling_the_feature_sends_nothing(self):
        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.staff.username, "password": PASSWORD},
        )
        self.assertEqual(mail.outbox, [])

    @override_settings(**{**NOTIFY, "AUTH_NOTIFY_ON_LOGIN": False})
    def test_login_notifications_can_be_turned_off_independently(self):
        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.staff.username, "password": PASSWORD},
        )
        self.assertEqual(mail.outbox, [])
        self.client.post(reverse("vivacalc:logout"))
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(**{**NOTIFY, "AUTH_NOTIFY_RECIPIENTS": []})
    def test_no_recipients_means_no_send(self):
        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.staff.username, "password": PASSWORD},
        )
        self.assertEqual(mail.outbox, [])

    @override_settings(**{**NOTIFY, "AUTH_NOTIFY_USER_TOO": True})
    def test_the_user_can_be_copied_in(self):
        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.staff.username, "password": PASSWORD},
        )
        self.assertCountEqual(
            mail.outbox[0].to, RECIPIENTS + ["rahul@example.com"]
        )

    @override_settings(
        **{**NOTIFY, "AUTH_NOTIFY_USER_TOO": True,
           "AUTH_NOTIFY_RECIPIENTS": ["rahul@example.com", "ops@example.com"]}
    )
    def test_a_duplicated_address_is_sent_to_once(self):
        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.staff.username, "password": PASSWORD},
        )
        self.assertEqual(
            sorted(mail.outbox[0].to), ["ops@example.com", "rahul@example.com"]
        )


class AppPasswordHandlingTests(TestCase):
    def test_spaces_in_a_gmail_app_password_are_stripped(self):
        """Google shows app passwords as 'abcd efgh ijkl mnop'."""
        import importlib
        import os

        os.environ["EMAIL_HOST_PASSWORD"] = "abcd efgh ijkl mnop"
        os.environ.setdefault("DJANGO_SECRET_KEY", "k" * 50)
        try:
            base = importlib.import_module("vivacalc.settings.base")
            importlib.reload(base)
            self.assertEqual(base.EMAIL_HOST_PASSWORD, "abcdefghijklmnop")
        finally:
            os.environ.pop("EMAIL_HOST_PASSWORD", None)
            importlib.reload(importlib.import_module("vivacalc.settings.base"))


class BackendConfigurationTests(TestCase):
    """Regressions for the two things that made mail silently not arrive."""

    def setUp(self):
        cache.clear()
        self.staff = make_staff("rahul")
        mail.outbox = []

    @override_settings(
        **{**NOTIFY,
           "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
           "EMAIL_HOST_PASSWORD": ""}
    )
    def test_smtp_without_a_password_is_refused_loudly_not_attempted(self):
        with self.assertLogs("vivacalc.auth", level="ERROR") as captured:
            sent = notifications.notify(notifications.LOGIN, self.staff, None)
        self.assertFalse(sent)
        self.assertIn("EMAIL_HOST_PASSWORD is not set", "\n".join(captured.output))

    @override_settings(
        **{**NOTIFY,
           "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
           "EMAIL_HOST_PASSWORD": ""}
    )
    def test_a_missing_password_still_does_not_break_sign_in(self):
        response = self.client.post(
            reverse("vivacalc:login"),
            {"username": self.staff.username, "password": PASSWORD},
            follow=True,
        )
        self.assertTrue(response.context["user"].is_authenticated)

    def test_dev_settings_let_the_backend_be_overridden_from_the_environment(self):
        """dev.py used to hard-code the console backend, so nothing ever sent."""
        import importlib
        import os

        os.environ["EMAIL_BACKEND"] = "django.core.mail.backends.smtp.EmailBackend"
        os.environ.setdefault("DJANGO_SECRET_KEY", "k" * 50)
        try:
            dev = importlib.import_module("vivacalc.settings.dev")
            importlib.reload(dev)
            self.assertIn("smtp", dev.EMAIL_BACKEND)
        finally:
            os.environ.pop("EMAIL_BACKEND", None)
            importlib.reload(importlib.import_module("vivacalc.settings.dev"))
