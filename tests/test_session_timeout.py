"""Session lifetime: absolute cap, idle timeout, and single-notification rule."""

import datetime as dt
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from vivapanel import notifications
from vivapanel import session_policy as policy

from .factories import PASSWORD, make_staff

NOTIFY = dict(
    AUTH_NOTIFY_ENABLED=True,
    AUTH_NOTIFY_RECIPIENTS=["ops@example.com"],
    AUTH_NOTIFY_ON_LOGIN=True,
    AUTH_NOTIFY_ON_LOGOUT=True,
    AUTH_NOTIFY_SYNCHRONOUS=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)


class AbsoluteCapTests(TestCase):
    """One hour from sign-in, and nothing the user does extends it."""

    def setUp(self):
        cache.clear()
        mail.outbox = []
        self.user = make_staff("rahul")

    def _login(self):
        return self.client.post(
            reverse("vivacalc:login"),
            {"username": self.user.username, "password": PASSWORD},
        )

    def test_login_pins_a_deadline_one_hour_out(self):
        before = timezone.now()
        self._login()
        end = policy.deadline(self.client.session)
        self.assertIsNotNone(end)
        self.assertAlmostEqual(
            (end - before).total_seconds(), 3600, delta=10
        )

    def test_a_session_within_the_hour_still_works(self):
        self._login()
        self.assertEqual(
            self.client.get(reverse("vivacalc:dashboard")).status_code, 200
        )

    def test_the_session_ends_once_the_hour_has_passed(self):
        self._login()
        session = self.client.session
        session[policy.STARTED_AT] = (
            timezone.now() - dt.timedelta(hours=1, seconds=1)
        ).isoformat()
        session[policy.LAST_SEEN_AT] = timezone.now().isoformat()
        session.save()

        response = self.client.get(reverse("vivacalc:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("vivacalc:login"), response["Location"])

    def test_activity_does_not_push_the_deadline_out(self):
        """The core requirement: refreshing must not buy more time."""
        self._login()
        original = policy.deadline(self.client.session)

        for _ in range(5):
            self.client.get(reverse("vivacalc:dashboard"))

        self.assertEqual(policy.deadline(self.client.session), original)

    def test_the_cookie_expiry_is_absolute_not_sliding(self):
        from django.contrib.sessions.models import Session

        self._login()
        key = self.client.session.session_key
        first = Session.objects.get(session_key=key).expire_date

        self.client.get(reverse("vivacalc:dashboard"))
        self.client.get(reverse("vivacalc:booking_list"))

        after = Session.objects.get(session_key=key).expire_date
        self.assertEqual(
            first, after, "session expiry moved — the cap can be extended"
        )

    def test_the_project_keeps_save_every_request_off(self):
        from django.conf import settings

        self.assertFalse(settings.SESSION_SAVE_EVERY_REQUEST)


class IdleTimeoutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_staff("rahul")
        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.user.username, "password": PASSWORD},
        )

    def test_an_idle_session_is_ended(self):
        session = self.client.session
        session[policy.LAST_SEEN_AT] = (
            timezone.now() - dt.timedelta(minutes=16)
        ).isoformat()
        session.save()

        response = self.client.get(reverse("vivacalc:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_activity_resets_only_the_idle_clock(self):
        session = self.client.session
        session[policy.LAST_SEEN_AT] = (
            timezone.now() - dt.timedelta(minutes=10)
        ).isoformat()
        session.save()

        self.assertEqual(
            self.client.get(reverse("vivacalc:dashboard")).status_code, 200
        )
        refreshed = policy.last_seen_at(self.client.session)
        self.assertLess((timezone.now() - refreshed).total_seconds(), 5)

    def test_idle_cannot_extend_past_the_absolute_cap(self):
        """Even constant activity cannot survive the hour."""
        session = self.client.session
        session[policy.STARTED_AT] = (
            timezone.now() - dt.timedelta(hours=1, seconds=1)
        ).isoformat()
        session[policy.LAST_SEEN_AT] = timezone.now().isoformat()  # active now
        session.save()

        self.assertEqual(
            self.client.get(reverse("vivacalc:dashboard")).status_code, 302
        )


@override_settings(**NOTIFY)
class TimeoutNotificationTests(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox = []
        self.user = make_staff("rahul")
        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.user.username, "password": PASSWORD},
        )
        mail.outbox = []
        cache.clear()  # drop the login claim so logout can be claimed

    def _age_out(self):
        session = self.client.session
        session[policy.STARTED_AT] = (
            timezone.now() - dt.timedelta(hours=1, seconds=1)
        ).isoformat()
        session.save()

    def test_timeout_sends_exactly_one_logout_email(self):
        self._age_out()
        self.client.get(reverse("vivacalc:dashboard"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Logout", mail.outbox[0].subject)
        self.assertIn("rahul", mail.outbox[0].subject)

    def test_timeout_logs_the_reason(self):
        self._age_out()
        with self.assertLogs("vivacalc.audit", level="INFO") as captured:
            self.client.get(reverse("vivacalc:dashboard"))
        line = "\n".join(captured.output)
        self.assertIn("LOGOUT: username=rahul", line)
        self.assertIn("reason=session_expired", line)

    def test_idle_timeout_logs_its_own_reason(self):
        session = self.client.session
        session[policy.LAST_SEEN_AT] = (
            timezone.now() - dt.timedelta(minutes=16)
        ).isoformat()
        session.save()
        with self.assertLogs("vivacalc.audit", level="INFO") as captured:
            self.client.get(reverse("vivacalc:dashboard"))
        self.assertIn("reason=inactive", "\n".join(captured.output))

    def test_a_second_request_does_not_send_another_email(self):
        self._age_out()
        self.client.get(reverse("vivacalc:dashboard"))
        self.client.get(reverse("vivacalc:dashboard"))
        self.client.get(reverse("vivacalc:dashboard"))
        self.assertEqual(len(mail.outbox), 1)


@override_settings(**NOTIFY)
class EmailContentTests(TestCase):
    """Only username and timestamp. Nothing else."""

    def setUp(self):
        cache.clear()
        mail.outbox = []
        self.user = make_staff("rahul", email="rahul@example.com")
        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.user.username, "password": PASSWORD},
            HTTP_USER_AGENT="Mozilla/5.0 (SecretDevice) Chrome/151",
            REMOTE_ADDR="203.0.113.77",
        )

    def test_the_body_contains_the_username_and_time(self):
        body = mail.outbox[0].body
        self.assertIn("rahul", body)
        self.assertRegex(body, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

    def test_the_body_leaks_no_device_or_network_detail(self):
        message = mail.outbox[0]
        haystack = message.body + message.subject
        for alternative in message.alternatives:
            haystack += alternative.content
        for forbidden in ("203.0.113.77", "SecretDevice", "Mozilla",
                          "Chrome", "IP address", "Device", "Staff",
                          "rahul@example.com"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, haystack)


class DeduplicationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_staff("rahul")

    @override_settings(**NOTIFY)
    def test_two_mechanisms_racing_on_one_session_send_once(self):
        mail.outbox = []

        class FakeRequest:
            class session:
                session_key = "abc123session"

        first = notifications.notify(
            notifications.LOGOUT, self.user, FakeRequest(), reason="session_expired"
        )
        second = notifications.notify(
            notifications.LOGOUT, self.user, FakeRequest(), reason="inactive"
        )
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(**NOTIFY)
    def test_different_sessions_are_reported_separately(self):
        mail.outbox = []

        def request_for(key):
            class R:
                class session:
                    session_key = key
            return R()

        self.assertTrue(
            notifications.notify(notifications.LOGIN, self.user, request_for("s1"))
        )
        self.assertTrue(
            notifications.notify(notifications.LOGIN, self.user, request_for("s2"))
        )
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(**{**NOTIFY, "AUTH_NOTIFY_ON_LOGIN": False})
    def test_the_terminal_line_is_written_even_when_email_is_off(self):
        mail.outbox = []
        with self.assertLogs("vivacalc.audit", level="INFO") as captured:
            notifications.notify(notifications.LOGIN, self.user, None)
        self.assertIn("LOGIN: username=rahul", "\n".join(captured.output))
        self.assertEqual(mail.outbox, [])


class SweeperTests(TestCase):
    """expire_sessions reports sessions that died with nobody watching."""

    def setUp(self):
        cache.clear()
        mail.outbox = []
        self.user = make_staff("rahul")

    @override_settings(**NOTIFY)
    def test_it_reports_and_removes_an_expired_session(self):
        from django.contrib.sessions.models import Session
        from django.core.management import call_command

        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.user.username, "password": PASSWORD},
        )
        key = self.client.session.session_key
        session = self.client.session
        session[policy.STARTED_AT] = (
            timezone.now() - dt.timedelta(hours=2)
        ).isoformat()
        session.save()
        mail.outbox = []
        cache.clear()

        call_command("expire_sessions", "--quiet")

        self.assertFalse(Session.objects.filter(session_key=key).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Logout", mail.outbox[0].subject)

    @override_settings(**NOTIFY)
    def test_it_leaves_live_sessions_alone(self):
        from django.contrib.sessions.models import Session
        from django.core.management import call_command

        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.user.username, "password": PASSWORD},
        )
        key = self.client.session.session_key
        mail.outbox = []

        call_command("expire_sessions", "--quiet")

        self.assertTrue(Session.objects.filter(session_key=key).exists())
        self.assertEqual(mail.outbox, [])


class ServerSideInvalidationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_staff("rahul")

    def test_the_session_row_is_destroyed_on_timeout(self):
        from django.contrib.sessions.models import Session

        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.user.username, "password": PASSWORD},
        )
        key = self.client.session.session_key
        self.assertTrue(Session.objects.filter(session_key=key).exists())

        session = self.client.session
        session[policy.STARTED_AT] = (
            timezone.now() - dt.timedelta(hours=2)
        ).isoformat()
        session.save()
        self.client.get(reverse("vivacalc:dashboard"))

        self.assertFalse(
            Session.objects.filter(session_key=key).exists(),
            "expired session row survived — not invalidated server-side",
        )

    def test_a_stolen_cookie_is_useless_after_timeout(self):
        """Replaying the cookie must not resurrect the session."""
        self.client.post(
            reverse("vivacalc:login"),
            {"username": self.user.username, "password": PASSWORD},
        )
        from django.conf import settings as s

        stolen = self.client.cookies[s.SESSION_COOKIE_NAME].value

        session = self.client.session
        session[policy.STARTED_AT] = (
            timezone.now() - dt.timedelta(hours=2)
        ).isoformat()
        session.save()
        self.client.get(reverse("vivacalc:dashboard"))  # triggers the logout

        attacker = self.client_class()
        attacker.cookies[s.SESSION_COOKIE_NAME] = stolen
        self.assertEqual(
            attacker.get(reverse("vivacalc:dashboard")).status_code, 302
        )
