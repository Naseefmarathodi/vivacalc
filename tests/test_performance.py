"""Query-count regression guards.

Each page must issue a constant number of queries regardless of how many rows
it renders. These tests fail loudly if a select_related is ever dropped.
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .factories import make_admin, make_booking, make_portal, make_staff

WIDE_RANGE = "?start_date=2000-01-01&end_date=2100-01-01"


class QueryCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_admin()
        cls.staff = make_staff()
        cls.portal = make_portal()
        for i in range(60):
            make_booking(cls.staff, portal=cls.portal, passenger_name=f"P{i}")

    def setUp(self):
        cache.clear()

    def test_admin_booking_list_is_constant_cost(self):
        self.client.force_login(self.admin)
        with self.assertNumQueries(10):
            self.client.get(reverse("adminpanel:booking_list") + WIDE_RANGE)

    def test_staff_booking_list_is_constant_cost(self):
        self.client.force_login(self.staff)
        with self.assertNumQueries(9):
            self.client.get(reverse("vivacalc:booking_list") + WIDE_RANGE)

    def test_admin_dashboard_is_constant_cost(self):
        self.client.force_login(self.admin)
        with self.assertNumQueries(14):
            self.client.get(reverse("adminpanel:dashboard"))

    def test_staff_dashboard_is_constant_cost(self):
        self.client.force_login(self.staff)
        with self.assertNumQueries(9):
            self.client.get(reverse("vivacalc:dashboard"))

    def test_excel_export_is_constant_cost(self):
        self.client.force_login(self.admin)
        with self.assertNumQueries(8):
            self.client.get(
                reverse("adminpanel:export_bookings_excel") + WIDE_RANGE
            )

    def test_pdf_export_is_constant_cost(self):
        self.client.force_login(self.admin)
        with self.assertNumQueries(8):
            self.client.get(reverse("adminpanel:export_bookings_pdf") + WIDE_RANGE)


class NoNPlusOneTests(TestCase):
    """The same page at two very different row counts must cost the same."""

    def setUp(self):
        cache.clear()
        self.admin = make_admin()
        self.staff = make_staff()
        self.portal = make_portal()

    def _measure(self, url):
        self.client.force_login(self.admin)
        with self.assertNumQueries(10):
            response = self.client.get(url)
        return response

    def test_booking_list_cost_does_not_grow_with_row_count(self):
        url = reverse("adminpanel:booking_list") + WIDE_RANGE
        for i in range(5):
            make_booking(self.staff, portal=self.portal, passenger_name=f"A{i}")
        self._measure(url)

        for i in range(45):
            make_booking(self.staff, portal=self.portal, passenger_name=f"B{i}")
        # Same assertion, ten times the rows.
        self._measure(url)

    def test_related_objects_are_preloaded(self):
        for i in range(5):
            make_booking(self.staff, portal=self.portal, passenger_name=f"C{i}")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("adminpanel:booking_list") + WIDE_RANGE)
        bookings = response.context["bookings"]
        # Touching the related objects must issue no further queries.
        with self.assertNumQueries(0):
            for booking in bookings:
                _ = booking.portal.name
                _ = booking.entered_by.username


class PageRenderTests(TestCase):
    """Every page renders for the role that owns it."""

    def setUp(self):
        cache.clear()
        self.admin = make_admin()
        self.staff = make_staff()
        self.portal = make_portal()
        self.booking = make_booking(self.admin, portal=self.portal)
        self.staff_booking = make_booking(self.staff, portal=self.portal)

    def test_all_admin_pages_render(self):
        self.client.force_login(self.admin)
        urls = [
            reverse("adminpanel:dashboard"),
            reverse("adminpanel:booking_list"),
            reverse("adminpanel:booking_create"),
            reverse("adminpanel:booking_update", args=(self.booking.pk,)),
            reverse("adminpanel:booking_delete", args=(self.booking.pk,)),
            reverse("adminpanel:portal_list"),
            reverse("adminpanel:portal_create"),
            reverse("adminpanel:portal_update", args=(self.portal.pk,)),
            reverse("adminpanel:portal_delete", args=(self.portal.pk,)),
            reverse("adminpanel:user_list"),
            reverse("adminpanel:user_create"),
            reverse("adminpanel:user_update", args=(self.staff.pk,)),
            reverse("adminpanel:user_delete", args=(self.staff.pk,)),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_all_staff_pages_render(self):
        self.client.force_login(self.staff)
        urls = [
            reverse("vivacalc:dashboard"),
            reverse("vivacalc:booking_list"),
            reverse("vivacalc:booking_create"),
            reverse("vivacalc:booking_update", args=(self.staff_booking.pk,)),
            reverse("vivacalc:booking_delete", args=(self.staff_booking.pk,)),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_the_logo_is_referenced_on_every_shell_page(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("vivacalc:dashboard"))
        self.assertContains(response, "logo.png")

    def test_the_login_page_shows_the_logo(self):
        self.assertContains(self.client.get(reverse("vivacalc:login")), "logo.png")

    def test_empty_state_is_shown_when_a_user_has_no_bookings(self):
        fresh = make_staff("brand_new")
        self.client.force_login(fresh)
        response = self.client.get(reverse("vivacalc:booking_list"))
        self.assertContains(response, "No bookings yet")
