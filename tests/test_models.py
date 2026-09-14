"""Model behaviour: the margin rule, roles, and data integrity."""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError, Sum
from django.test import TestCase

from adminpanel.models import CustomUser, Portal, TravelBooking

from .factories import make_admin, make_booking, make_portal, make_staff, make_superuser


class MarginCalculationTests(TestCase):
    """margin = sell_price - buy_price, in Decimal, always."""

    def setUp(self):
        self.user = make_staff()

    def test_margin_is_computed_on_create(self):
        booking = make_booking(self.user, buy="1000.00", sell="1250.00")
        self.assertEqual(booking.margin, Decimal("1250.00") - Decimal("1000.00"))
        self.assertEqual(booking.margin, Decimal("250.00"))

    def test_margin_is_recomputed_on_update(self):
        booking = make_booking(self.user, buy="1000.00", sell="1250.00")
        booking.sell_price = Decimal("1400.00")
        booking.save()
        booking.refresh_from_db()
        self.assertEqual(booking.margin, Decimal("400.00"))

    def test_margin_can_be_negative(self):
        booking = make_booking(self.user, buy="900.00", sell="750.00")
        self.assertEqual(booking.margin, Decimal("-150.00"))

    def test_margin_is_decimal_not_float(self):
        booking = make_booking(self.user, buy="0.10", sell="0.30")
        self.assertIsInstance(booking.margin, Decimal)
        self.assertEqual(booking.margin, Decimal("0.20"))

    def test_totals_are_exact_where_float_accumulation_would_drift(self):
        """0.07 three times is 0.21 exactly; in binary floats it is not."""
        for _ in range(3):
            make_booking(self.user, buy="0.00", sell="0.07")

        db_total = TravelBooking.objects.aggregate(t=Sum("margin"))["t"]
        self.assertEqual(db_total, Decimal("0.21"))

        float_total = 0.07 + 0.07 + 0.07
        self.assertNotEqual(float_total, 0.21)          # the bug we avoid
        self.assertEqual(float(db_total), 0.21)

    def test_margin_is_not_an_editable_form_field(self):
        self.assertFalse(TravelBooking._meta.get_field("margin").editable)


class PriceConstraintTests(TestCase):
    def setUp(self):
        self.user = make_staff()

    def test_negative_buy_price_is_rejected_by_the_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TravelBooking.objects.create(
                passenger_name="X", service="s",
                buy_price=Decimal("-1.00"), sell_price=Decimal("5.00"),
                margin=Decimal("6.00"), entered_by=self.user,
            )

    def test_negative_sell_price_is_rejected_by_the_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TravelBooking.objects.create(
                passenger_name="X", service="s",
                buy_price=Decimal("5.00"), sell_price=Decimal("-1.00"),
                margin=Decimal("-6.00"), entered_by=self.user,
            )


class PortalProtectionTests(TestCase):
    """A supplier must never be deletable out from under its sales history."""

    def test_portal_with_bookings_cannot_be_deleted(self):
        portal = make_portal()
        make_booking(make_staff(), portal=portal)
        with self.assertRaises(ProtectedError):
            portal.delete()
        self.assertTrue(Portal.objects.filter(pk=portal.pk).exists())

    def test_portal_without_bookings_can_be_deleted(self):
        portal = make_portal(name="Unused")
        portal.delete()
        self.assertFalse(Portal.objects.filter(pk=portal.pk).exists())

    def test_deleting_a_user_keeps_their_bookings(self):
        user = make_staff()
        booking = make_booking(user)
        user.delete()
        booking.refresh_from_db()
        self.assertIsNone(booking.entered_by)
        self.assertEqual(booking.margin, Decimal("250.00"))


class RoleTests(TestCase):
    """role is the authoritative application permission."""

    def test_admin_role_grants_panel_access(self):
        self.assertTrue(make_admin().is_panel_admin)

    def test_staff_role_does_not_grant_panel_access(self):
        self.assertFalse(make_staff().is_panel_admin)

    def test_superuser_always_has_panel_access(self):
        user = make_superuser()
        user.role = CustomUser.Role.STAFF
        user.save()
        self.assertTrue(user.is_panel_admin)

    def test_default_role_is_staff(self):
        self.assertEqual(
            CustomUser.objects.create_user(username="n", password="pw").role,
            CustomUser.Role.STAFF,
        )


class OrderingTests(TestCase):
    def test_bookings_default_to_newest_first(self):
        user = make_staff()
        first = make_booking(user, passenger_name="First")
        second = make_booking(user, passenger_name="Second")
        self.assertEqual(
            list(TravelBooking.objects.values_list("pk", flat=True)),
            [second.pk, first.pk],
        )
