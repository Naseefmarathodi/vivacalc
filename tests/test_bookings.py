"""Booking CRUD and the filter system."""

from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from adminpanel.filters import BookingFilterForm
from adminpanel.models import Portal, TravelBooking

from .factories import make_admin, make_booking, make_portal, make_staff


class BookingCrudTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = make_staff()
        self.portal = make_portal()
        self.client.force_login(self.staff)

    def _payload(self, **overrides):
        data = {
            "passenger_name": "Anjali Nair",
            "service": "One-way ticket",
            "sector": "COK-DXB",
            "portal": self.portal.pk,
            "buy_price": "12000.00",
            "sell_price": "13500.50",
        }
        data.update(overrides)
        return data

    def test_create_stores_the_booking_and_computes_margin(self):
        response = self.client.post(
            reverse("vivacalc:booking_create"), self._payload(), follow=True
        )
        self.assertEqual(response.status_code, 200)
        booking = TravelBooking.objects.get()
        self.assertEqual(booking.passenger_name, "Anjali Nair")
        self.assertEqual(booking.margin, Decimal("1500.50"))
        self.assertContains(response, "created successfully")

    def test_create_attributes_the_booking_to_the_signed_in_user(self):
        self.client.post(reverse("vivacalc:booking_create"), self._payload())
        self.assertEqual(TravelBooking.objects.get().entered_by, self.staff)

    def test_margin_cannot_be_supplied_by_the_client(self):
        """Even if margin is posted, the server recomputes it."""
        self.client.post(
            reverse("vivacalc:booking_create"),
            self._payload(margin="999999.00"),
        )
        self.assertEqual(TravelBooking.objects.get().margin, Decimal("1500.50"))

    def test_negative_price_is_rejected_with_a_field_error(self):
        response = self.client.post(
            reverse("vivacalc:booking_create"), self._payload(buy_price="-5.00")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TravelBooking.objects.count(), 0)
        self.assertContains(response, "cannot be negative")

    def test_non_numeric_price_is_rejected(self):
        response = self.client.post(
            reverse("vivacalc:booking_create"), self._payload(sell_price="abc")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TravelBooking.objects.count(), 0)

    def test_update_recomputes_the_margin(self):
        booking = make_booking(self.staff, portal=self.portal)
        self.client.post(
            reverse("vivacalc:booking_update", args=(booking.pk,)),
            self._payload(buy_price="100.00", sell_price="175.25"),
        )
        booking.refresh_from_db()
        self.assertEqual(booking.margin, Decimal("75.25"))

    def test_delete_by_get_only_asks_for_confirmation(self):
        booking = make_booking(self.staff, portal=self.portal)
        response = self.client.get(
            reverse("vivacalc:booking_delete", args=(booking.pk,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot be undone")
        self.assertTrue(TravelBooking.objects.filter(pk=booking.pk).exists())

    def test_delete_by_post_removes_the_booking(self):
        booking = make_booking(self.staff, portal=self.portal)
        response = self.client.post(
            reverse("vivacalc:booking_delete", args=(booking.pk,)), follow=True
        )
        self.assertFalse(TravelBooking.objects.filter(pk=booking.pk).exists())
        self.assertContains(response, "deleted successfully")

    def test_inactive_portals_are_not_offered_on_a_new_booking(self):
        retired = make_portal(name="Retired", is_active=False)
        response = self.client.get(reverse("vivacalc:booking_create"))
        choices = response.context["form"].fields["portal"].queryset
        self.assertIn(self.portal, choices)
        self.assertNotIn(retired, choices)

    def test_editing_a_booking_keeps_its_retired_portal_selectable(self):
        retired = make_portal(name="Retired", is_active=False)
        booking = make_booking(self.staff, portal=retired)
        response = self.client.get(
            reverse("vivacalc:booking_update", args=(booking.pk,))
        )
        self.assertIn(retired, response.context["form"].fields["portal"].queryset)


class FilterFormTests(TestCase):
    """Bad input must produce field errors, never an exception."""

    def setUp(self):
        cache.clear()
        self.staff = make_staff("owner")
        self.other = make_staff("other")
        self.portal = make_portal()
        make_booking(self.staff, portal=self.portal, passenger_name="Arun Kumar",
                     sector="COK-DXB")
        make_booking(self.staff, portal=self.portal, passenger_name="Meera Das",
                     sector="BOM-SIN")
        make_booking(self.other, portal=self.portal, passenger_name="Zoya Khan",
                     sector="DEL-LHR")

    def test_empty_filters_return_everything(self):
        form = BookingFilterForm({})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.apply(TravelBooking.objects.all()).count(), 3)

    def test_invalid_date_is_a_field_error_not_an_exception(self):
        form = BookingFilterForm({"start_date": "junk"})
        self.assertFalse(form.is_valid())
        self.assertIn("start_date", form.errors)
        self.assertEqual(form.apply(TravelBooking.objects.all()).count(), 3)

    def test_invalid_user_is_a_field_error_not_an_exception(self):
        form = BookingFilterForm({"user": "abc"})
        self.assertFalse(form.is_valid())
        self.assertIn("user", form.errors)

    def test_reversed_date_range_is_reported(self):
        form = BookingFilterForm(
            {"start_date": "2030-01-01", "end_date": "2020-01-01"}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("end_date", form.errors)

    def test_passenger_search_is_case_insensitive_and_partial(self):
        form = BookingFilterForm({"passenger_name": "arun"})
        self.assertTrue(form.is_valid())
        results = form.apply(TravelBooking.objects.all())
        self.assertEqual([b.passenger_name for b in results], ["Arun Kumar"])

    def test_sector_search_works(self):
        form = BookingFilterForm({"sector": "BOM"})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.apply(TravelBooking.objects.all()).count(), 1)

    def test_user_filter_narrows_to_that_user(self):
        form = BookingFilterForm({"user": str(self.other.pk)})
        self.assertTrue(form.is_valid())
        results = form.apply(TravelBooking.objects.all())
        self.assertEqual([b.passenger_name for b in results], ["Zoya Khan"])

    def test_portal_filter_narrows_to_that_portal(self):
        other_portal = make_portal(name="Amadeus")
        make_booking(self.staff, portal=other_portal, passenger_name="Solo")
        form = BookingFilterForm({"portal": str(other_portal.pk)})
        self.assertTrue(form.is_valid())
        self.assertEqual(
            [b.passenger_name for b in form.apply(TravelBooking.objects.all())],
            ["Solo"],
        )

    def test_staff_form_has_no_user_filter(self):
        """Staff screens are already scoped; offering a user filter is misleading."""
        form = BookingFilterForm({}, include_user_filter=False)
        self.assertNotIn("user", form.fields)


class HostileQueryStringTests(TestCase):
    """Garbage in the URL bar must never produce a 500."""

    BAD = [
        "?user=abc",
        "?start_date=junk",
        "?end_date=not-a-date",
        "?client_name=x",          # a field that does not exist
        "?portal=999999",
        "?page=99999",
        "?page=abc",
        "?start_date=2030-01-01&end_date=2020-01-01",
        "?passenger_name=" + "x" * 500,
    ]

    def setUp(self):
        cache.clear()
        self.admin = make_admin()
        make_booking(self.admin, portal=make_portal())

    def test_admin_booking_list_survives_hostile_input(self):
        self.client.force_login(self.admin)
        url = reverse("adminpanel:booking_list")
        for query in self.BAD:
            with self.subTest(query=query):
                self.assertEqual(self.client.get(url + query).status_code, 200)

    def test_exports_survive_hostile_input(self):
        self.client.force_login(self.admin)
        for name in ("adminpanel:export_bookings_excel",
                     "adminpanel:export_bookings_pdf"):
            url = reverse(name)
            for query in self.BAD:
                with self.subTest(url=name, query=query):
                    self.assertIn(
                        self.client.get(url + query).status_code, (200, 302)
                    )

    def test_staff_booking_list_survives_hostile_input(self):
        staff = make_staff()
        self.client.force_login(staff)
        url = reverse("vivacalc:booking_list")
        for query in self.BAD:
            with self.subTest(query=query):
                self.assertEqual(self.client.get(url + query).status_code, 200)


class PaginationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = make_staff()
        portal = make_portal()
        for i in range(120):
            make_booking(self.staff, portal=portal, passenger_name=f"P{i}")
        self.client.force_login(self.staff)

    def test_the_list_is_paginated(self):
        response = self.client.get(reverse("vivacalc:booking_list"))
        page = response.context["page_obj"]
        self.assertEqual(page.paginator.count, 120)
        self.assertEqual(len(page.object_list), 50)
        self.assertEqual(page.paginator.num_pages, 3)

    def test_an_out_of_range_page_falls_back_to_the_last_page(self):
        response = self.client.get(reverse("vivacalc:booking_list") + "?page=999")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].number, 3)

    def test_totals_cover_the_whole_filtered_set_not_just_the_page(self):
        response = self.client.get(reverse("vivacalc:booking_list"))
        self.assertEqual(
            response.context["totals"]["total_margin"], Decimal("250.00") * 120
        )
