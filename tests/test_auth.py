"""Authentication: sign-in, sign-out, routing and brute-force protection."""

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .factories import PASSWORD, make_admin, make_staff


class LoginFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = make_staff()
        self.admin = make_admin()

    def test_login_page_is_reachable_anonymously(self):
        response = self.client.get(reverse("vivacalc:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in")

    def test_staff_can_sign_in_and_lands_on_the_staff_dashboard(self):
        response = self.client.post(
            reverse("vivacalc:login"),
            {"username": self.staff.username, "password": PASSWORD},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse("vivacalc:dashboard"))

    def test_admin_can_sign_in_and_lands_on_the_admin_dashboard(self):
        response = self.client.post(
            reverse("vivacalc:login"),
            {"username": self.admin.username, "password": PASSWORD},
            follow=True,
        )
        self.assertRedirects(response, reverse("adminpanel:dashboard"))

    def test_wrong_password_does_not_authenticate(self):
        response = self.client.post(
            reverse("vivacalc:login"),
            {"username": self.staff.username, "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_missing_fields_do_not_raise(self):
        """The old hand-rolled view raised MultiValueDictKeyError here."""
        response = self.client.post(reverse("vivacalc:login"), {})
        self.assertEqual(response.status_code, 200)

    def test_anonymous_user_is_sent_to_a_real_login_page_not_a_404(self):
        target = reverse("vivacalc:booking_list")
        response = self.client.get(target)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("vivacalc:login"), response["Location"])
        # and that destination must actually exist
        self.assertEqual(self.client.get(response["Location"]).status_code, 200)

    def test_anonymous_user_hitting_the_admin_panel_is_sent_to_login(self):
        response = self.client.get(reverse("adminpanel:booking_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("vivacalc:login"), response["Location"])


class LogoutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = make_staff()
        self.client.force_login(self.staff)

    def test_logout_by_get_does_not_end_the_session(self):
        response = self.client.get(reverse("vivacalc:logout"))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(
            self.client.get(reverse("vivacalc:dashboard")).status_code, 200
        )

    def test_logout_by_post_ends_the_session(self):
        response = self.client.post(reverse("vivacalc:logout"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.get(reverse("vivacalc:dashboard")).status_code, 302
        )


@override_settings(LOGIN_ATTEMPT_LIMIT=3, LOGIN_ATTEMPT_COOLOFF_MINUTES=15)
class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = make_staff()
        self.url = reverse("vivacalc:login")

    def _fail_once(self):
        return self.client.post(
            self.url, {"username": self.staff.username, "password": "nope"}
        )

    def test_repeated_failures_lock_the_account_out(self):
        for _ in range(3):
            self._fail_once()

        # The correct password must now be refused too.
        response = self.client.post(
            self.url, {"username": self.staff.username, "password": PASSWORD}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertContains(response, "Too many failed sign-in attempts")

    def test_a_successful_sign_in_clears_the_counter(self):
        self._fail_once()
        self.client.post(
            self.url, {"username": self.staff.username, "password": PASSWORD}
        )
        self.client.post(reverse("vivacalc:logout"))
        for _ in range(2):
            self._fail_once()
        # Two failures after a reset is still below the limit of three.
        response = self.client.post(
            self.url, {"username": self.staff.username, "password": PASSWORD},
            follow=True,
        )
        self.assertTrue(response.context["user"].is_authenticated)


class HealthCheckTests(TestCase):
    def test_healthz_is_public_and_returns_200(self):
        response = self.client.get(reverse("healthz"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.strip(), b"ok")
