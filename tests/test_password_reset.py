"""Administrator-initiated password resets.

Passwords are one-way hashes, so an admin can set a new one but can never read
the existing one. These tests pin both halves of that.
"""

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .factories import PASSWORD, make_admin, make_staff

NEW_PASSWORD = "Thunder-Marmalade-7731"


class PasswordIsNeverDisplayedTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_admin()
        self.staff = make_staff()
        self.client.force_login(self.admin)

    def test_the_edit_page_does_not_leak_the_password_hash(self):
        response = self.client.get(
            reverse("adminpanel:user_update", args=(self.staff.pk,))
        )
        self.assertEqual(response.status_code, 200)
        self.staff.refresh_from_db()
        self.assertNotContains(response, self.staff.password)
        self.assertNotContains(response, "pbkdf2_sha256$")

    def test_the_edit_page_explains_why(self):
        response = self.client.get(
            reverse("adminpanel:user_update", args=(self.staff.pk,))
        )
        # Phrase chosen to survive template line wrapping.
        self.assertContains(response, "Existing passwords can")
        self.assertContains(response, "one-way")

    def test_the_edit_page_offers_a_set_password_form(self):
        response = self.client.get(
            reverse("adminpanel:user_update", args=(self.staff.pk,))
        )
        self.assertContains(
            response,
            reverse("adminpanel:user_set_password", args=(self.staff.pk,)),
        )
        self.assertIn("new_password1", response.context["password_form"].fields)

    def test_the_profile_form_has_no_password_field(self):
        response = self.client.get(
            reverse("adminpanel:user_update", args=(self.staff.pk,))
        )
        self.assertNotIn("password", response.context["form"].fields)


class SetPasswordTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_admin()
        self.staff = make_staff()
        self.client.force_login(self.admin)
        self.url = reverse("adminpanel:user_set_password", args=(self.staff.pk,))

    def test_an_admin_can_set_a_new_password_for_another_user(self):
        response = self.client.post(
            self.url,
            {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Password updated")
        self.assertIsNotNone(
            authenticate(username=self.staff.username, password=NEW_PASSWORD)
        )
        self.assertIsNone(
            authenticate(username=self.staff.username, password=PASSWORD)
        )

    def test_mismatched_confirmation_is_rejected(self):
        response = self.client.post(
            self.url,
            {"new_password1": NEW_PASSWORD, "new_password2": "something-else-99"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(
            authenticate(username=self.staff.username, password=PASSWORD)
        )

    def test_a_password_below_the_policy_minimum_is_rejected(self):
        response = self.client.post(
            self.url, {"new_password1": "admin@123", "new_password2": "admin@123"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "at least 10 characters")
        self.assertIsNotNone(
            authenticate(username=self.staff.username, password=PASSWORD)
        )

    def test_a_common_password_is_rejected(self):
        response = self.client.post(
            self.url, {"new_password1": "password123", "new_password2": "password123"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(
            authenticate(username=self.staff.username, password=PASSWORD)
        )

    def test_a_failed_reset_redisplays_both_forms(self):
        response = self.client.post(
            self.url, {"new_password1": "x", "new_password2": "x"}
        )
        self.assertIn("form", response.context)
        self.assertIn("password_form", response.context)
        self.assertEqual(response.context["target_user"], self.staff)

    def test_changing_your_own_password_keeps_you_signed_in(self):
        own_url = reverse("adminpanel:user_set_password", args=(self.admin.pk,))
        response = self.client.post(
            own_url,
            {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
            follow=True,
        )
        self.assertContains(response, "Your password was changed")
        # Still authenticated on the next request rather than bounced to login.
        self.assertEqual(
            self.client.get(reverse("adminpanel:user_list")).status_code, 200
        )

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


class SetPasswordAuthorizationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = make_staff("victim")
        self.attacker = make_staff("attacker")
        self.url = reverse("adminpanel:user_set_password", args=(self.staff.pk,))

    def test_staff_cannot_reset_anyones_password(self):
        self.client.force_login(self.attacker)
        response = self.client.post(
            self.url,
            {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("access-denied", response["Location"])
        self.assertIsNotNone(
            authenticate(username=self.staff.username, password=PASSWORD)
        )

    def test_anonymous_users_cannot_reset_a_password(self):
        response = self.client.post(
            self.url,
            {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(
            authenticate(username=self.staff.username, password=PASSWORD)
        )
