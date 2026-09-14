"""Authorisation: role gating and per-object ownership.

These are the highest-severity tests in the suite. A regression here silently
exposes the whole ledger.
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .factories import make_admin, make_booking, make_portal, make_staff

ADMIN_URLS = [
    ("adminpanel:dashboard", ()),
    ("adminpanel:booking_list", ()),
    ("adminpanel:booking_create", ()),
    ("adminpanel:export_bookings_excel", ()),
    ("adminpanel:export_bookings_pdf", ()),
    ("adminpanel:portal_list", ()),
    ("adminpanel:portal_create", ()),
    ("adminpanel:user_list", ()),
    ("adminpanel:user_create", ()),
]


class StaffCannotReachTheAdminPanelTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = make_staff()
        self.client.force_login(self.staff)

    def test_every_admin_url_is_refused_for_staff(self):
        for name, args in ADMIN_URLS:
            with self.subTest(url=name):
                response = self.client.get(reverse(name, args=args))
                self.assertNotEqual(response.status_code, 200)
                self.assertEqual(response.status_code, 302)
                self.assertIn("access-denied", response["Location"])

    def test_staff_cannot_post_to_admin_urls_either(self):
        response = self.client.post(reverse("adminpanel:booking_create"), {})
        self.assertNotEqual(response.status_code, 200)

    def test_staff_cannot_reach_admin_detail_urls(self):
        admin = make_admin()
        booking = make_booking(admin)
        for name in ("adminpanel:booking_update", "adminpanel:booking_delete"):
            with self.subTest(url=name):
                response = self.client.get(reverse(name, args=(booking.pk,)))
                self.assertEqual(response.status_code, 302)
                self.assertIn("access-denied", response["Location"])


class AdminCanReachTheAdminPanelTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client.force_login(make_admin())

    def test_every_admin_url_is_allowed_for_an_admin(self):
        for name, args in ADMIN_URLS:
            with self.subTest(url=name):
                self.assertEqual(
                    self.client.get(reverse(name, args=args)).status_code, 200
                )


class BookingOwnershipTests(TestCase):
    """A staff user may only ever touch their own bookings."""

    def setUp(self):
        cache.clear()
        self.owner = make_staff("owner")
        self.intruder = make_staff("intruder")
        self.portal = make_portal()
        self.booking = make_booking(self.owner, portal=self.portal)
        self.client.force_login(self.intruder)

    def test_another_users_booking_is_not_visible(self):
        response = self.client.get(
            reverse("vivacalc:booking_update", args=(self.booking.pk,))
        )
        self.assertEqual(response.status_code, 404)

    def test_another_users_booking_cannot_be_edited(self):
        response = self.client.post(
            reverse("vivacalc:booking_update", args=(self.booking.pk,)),
            {"passenger_name": "Hijacked", "service": "s",
             "buy_price": "1.00", "sell_price": "2.00"},
        )
        self.assertEqual(response.status_code, 404)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.passenger_name, "Rahul Menon")

    def test_another_users_booking_cannot_be_deleted(self):
        response = self.client.post(
            reverse("vivacalc:booking_delete", args=(self.booking.pk,))
        )
        self.assertEqual(response.status_code, 404)
        self.booking.refresh_from_db()  # still there

    def test_the_booking_list_shows_only_your_own_rows(self):
        mine = make_booking(self.intruder, passenger_name="Mine")
        response = self.client.get(reverse("vivacalc:booking_list"))
        self.assertContains(response, "Mine")
        self.assertNotContains(response, self.booking.passenger_name)
        self.assertEqual(list(response.context["bookings"]), [mine])

    def test_the_owner_can_edit_their_own_booking(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("vivacalc:booking_update", args=(self.booking.pk,))
        )
        self.assertEqual(response.status_code, 200)


class UserDeletionGuardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_admin("admin_one")
        self.client.force_login(self.admin)

    def test_an_admin_cannot_delete_their_own_account(self):
        response = self.client.post(
            reverse("adminpanel:user_delete", args=(self.admin.pk,)), follow=True
        )
        self.assertTrue(type(self.admin).objects.filter(pk=self.admin.pk).exists())
        self.assertContains(response, "cannot delete your own account")

    def test_an_admin_can_delete_a_different_admin(self):
        other_admin = make_admin("admin_two")
        self.client.post(reverse("adminpanel:user_delete", args=(other_admin.pk,)))
        self.assertFalse(
            type(other_admin).objects.filter(pk=other_admin.pk).exists()
        )

    def test_an_admin_cannot_remove_their_own_admin_role(self):
        """The one edit that cannot be undone from inside the app."""
        response = self.client.post(
            reverse("adminpanel:user_update", args=(self.admin.pk,)),
            {
                "username": self.admin.username,
                "first_name": "", "last_name": "", "email": "", "phone": "",
                "role": "staff",
                "is_active": "on",
            },
            follow=True,
        )
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, "admin")
        self.assertContains(response, "cannot remove your own Admin role")

    def test_an_admin_cannot_deactivate_themselves(self):
        response = self.client.post(
            reverse("adminpanel:user_update", args=(self.admin.pk,)),
            {
                "username": self.admin.username,
                "first_name": "", "last_name": "", "email": "", "phone": "",
                "role": "admin",
                # is_active omitted == unchecked
            },
            follow=True,
        )
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertContains(response, "cannot deactivate your own account")

    def test_an_admin_can_demote_a_different_admin(self):
        other_admin = make_admin("admin_three")
        self.client.post(
            reverse("adminpanel:user_update", args=(other_admin.pk,)),
            {
                "username": other_admin.username,
                "first_name": "", "last_name": "", "email": "", "phone": "",
                "role": "staff", "is_active": "on",
            },
        )
        other_admin.refresh_from_db()
        self.assertEqual(other_admin.role, "staff")
        self.assertFalse(other_admin.is_panel_admin)

    def test_deleting_a_user_preserves_their_bookings(self):
        staff = make_staff("departing")
        booking = make_booking(staff)
        self.client.post(reverse("adminpanel:user_delete", args=(staff.pk,)))
        booking.refresh_from_db()
        self.assertIsNone(booking.entered_by)
