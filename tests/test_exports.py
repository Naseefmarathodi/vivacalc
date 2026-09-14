"""Exports: filter parity, Decimal precision, pagination and logo integrity."""

import hashlib
import io
import zipfile
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.db.models import Sum
from django.urls import reverse
from openpyxl import load_workbook

from adminpanel.exports import ExportTooLarge, build_pdf, build_workbook
from adminpanel.models import TravelBooking

from .factories import make_admin, make_booking, make_portal, make_staff

EXCEL_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _original_logo_digest() -> str:
    return hashlib.sha256(settings.BRAND_LOGO_PATH.read_bytes()).hexdigest()


class ExportGenerationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_admin()
        self.portal = make_portal()
        make_booking(self.admin, portal=self.portal, buy="1000.00", sell="1250.00")
        make_booking(self.admin, portal=self.portal, buy="500.50", sell="700.25")
        self.client.force_login(self.admin)

    def test_excel_export_downloads_a_workbook(self):
        response = self.client.get(reverse("adminpanel:export_bookings_excel"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], EXCEL_TYPE)
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn(".xlsx", response["Content-Disposition"])

    def test_pdf_export_downloads_a_pdf(self):
        response = self.client.get(reverse("adminpanel:export_bookings_pdf"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_excel_contains_every_booking_plus_a_total_row(self):
        stream = build_workbook(TravelBooking.objects.all(), [])
        sheet = load_workbook(stream).active
        names = [c.value for c in sheet["B"] if c.value]
        self.assertIn("Rahul Menon", names)
        self.assertIn("TOTAL", names)

    def test_export_is_empty_but_valid_when_nothing_matches(self):
        empty = TravelBooking.objects.none()
        self.assertTrue(build_workbook(empty, []).getvalue())
        self.assertTrue(build_pdf(empty, []).getvalue().startswith(b"%PDF"))


class LogoIntegrityTests(TestCase):
    """The Viva logo must be embedded byte-for-byte, never re-encoded."""

    def setUp(self):
        cache.clear()
        self.admin = make_admin()
        make_booking(self.admin, portal=make_portal())

    def test_the_logo_asset_itself_is_unmodified(self):
        """Pinned to the digest recorded before any of this work began."""
        self.assertEqual(
            _original_logo_digest(),
            "156bff2a11a47da7a9adb8b7ac6465b4f043d97a3ddd14c185f1e54e062929df",
        )

    def test_excel_embeds_the_original_logo_bytes(self):
        stream = build_workbook(TravelBooking.objects.all(), [])
        with zipfile.ZipFile(io.BytesIO(stream.getvalue())) as archive:
            media = [n for n in archive.namelist() if n.startswith("xl/media/")]
            self.assertEqual(len(media), 1)
            embedded = hashlib.sha256(archive.read(media[0])).hexdigest()
        self.assertEqual(embedded, _original_logo_digest())

    def test_pdf_embeds_an_image(self):
        content = build_pdf(TravelBooking.objects.all(), []).getvalue()
        self.assertIn(b"/Image", content)


class DecimalPrecisionTests(TestCase):
    """Screen totals, Excel totals and PDF totals must agree exactly."""

    def setUp(self):
        cache.clear()
        self.admin = make_admin()
        portal = make_portal()
        # Values chosen because float accumulation drifts on them.
        for _ in range(3):
            make_booking(self.admin, portal=portal, buy="0.00", sell="0.07")
        self.client.force_login(self.admin)

    def test_the_total_is_aggregated_not_accumulated_in_python(self):
        """The original bug was `total += float(b.margin)`. This is the guard.

        The .xlsx format stores numbers as IEEE-754 doubles, so the cell comes
        back as a float — that is the file format, not our arithmetic. What
        must hold is that the total equals the database's exact Decimal sum
        rather than a drifting float accumulation.
        """
        stream = build_workbook(TravelBooking.objects.all(), [])
        sheet = load_workbook(stream).active
        total_row = next(
            row for row in sheet.iter_rows() if row[1].value == "TOTAL"
        )
        written = Decimal(str(total_row[7].value))
        exact = TravelBooking.objects.aggregate(t=Sum("margin"))["t"]

        self.assertEqual(exact, Decimal("0.21"))
        self.assertEqual(written, exact)

        # What the old implementation did, for contrast:
        drifting = 0.0
        for booking in TravelBooking.objects.all():
            drifting += float(booking.margin)
        self.assertNotEqual(Decimal(repr(drifting)), exact)

    def test_money_cells_carry_a_two_decimal_currency_format(self):
        stream = build_workbook(TravelBooking.objects.all(), [])
        sheet = load_workbook(stream).active
        header = next(r[0].row for r in sheet.iter_rows() if r[0].value == "S.No")
        first_data = sheet.cell(row=header + 1, column=6)
        self.assertEqual(first_data.number_format, "#,##0.00")

    def test_the_screen_total_matches_the_export_total(self):
        response = self.client.get(
            reverse("adminpanel:booking_list")
            + "?start_date=2000-01-01&end_date=2100-01-01"
        )
        on_screen = response.context["totals"]["total_margin"]

        stream = build_workbook(
            TravelBooking.objects.all(), []
        )
        sheet = load_workbook(stream).active
        total_row = next(r for r in sheet.iter_rows() if r[1].value == "TOTAL")
        in_excel = Decimal(str(total_row[7].value))

        self.assertEqual(on_screen, in_excel)
        self.assertEqual(on_screen, Decimal("0.21"))


class ExportFilterParityTests(TestCase):
    """An export must cover exactly the rows the list showed."""

    def setUp(self):
        cache.clear()
        self.admin = make_admin()
        self.staff = make_staff()
        portal = make_portal()
        make_booking(self.admin, portal=portal, passenger_name="Admin Row")
        make_booking(self.staff, portal=portal, passenger_name="Staff Row")
        self.client.force_login(self.admin)

    @staticmethod
    def _data_rows(sheet):
        """Passenger names between the header row and the TOTAL row."""
        header = next(
            row[0].row for row in sheet.iter_rows() if row[0].value == "S.No"
        )
        names = []
        for row in sheet.iter_rows(min_row=header + 1):
            label = row[1].value
            if label == "TOTAL" or label is None:
                break
            names.append(label)
        return names

    def _excel_names(self, query=""):
        response = self.client.get(
            reverse("adminpanel:export_bookings_excel") + query
        )
        self.assertEqual(response.status_code, 200)
        return self._data_rows(load_workbook(io.BytesIO(response.content)).active)

    def test_a_user_filter_narrows_the_export_the_same_way(self):
        query = f"?user={self.staff.pk}"
        listed = self.client.get(reverse("adminpanel:booking_list") + query)
        listed_names = [b.passenger_name for b in listed.context["bookings"]]
        self.assertEqual(listed_names, ["Staff Row"])
        self.assertEqual(self._excel_names(query), ["Staff Row"])

    def test_a_passenger_filter_narrows_the_export_the_same_way(self):
        self.assertEqual(self._excel_names("?passenger_name=Admin"), ["Admin Row"])

    def test_an_unfiltered_export_covers_everything(self):
        self.assertCountEqual(
            self._excel_names(), ["Admin Row", "Staff Row"]
        )

    def test_the_list_page_carries_its_filters_into_the_export_links(self):
        query = "?passenger_name=Admin"
        response = self.client.get(reverse("adminpanel:booking_list") + query)
        self.assertContains(response, "passenger_name=Admin")


@override_settings(EXPORT_MAX_ROWS=5)
class ExportSizeLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_admin()
        portal = make_portal()
        for i in range(10):
            make_booking(self.admin, portal=portal, passenger_name=f"P{i}")
        self.client.force_login(self.admin)

    def test_builder_refuses_an_oversized_export(self):
        with self.assertRaises(ExportTooLarge):
            build_workbook(TravelBooking.objects.all(), [])

    def test_the_view_redirects_with_an_explanation(self):
        response = self.client.get(
            reverse("adminpanel:export_bookings_excel")
            + "?start_date=2000-01-01&end_date=2100-01-01",
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "above the")


class PdfPaginationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = make_admin()
        portal = make_portal()
        for i in range(150):
            make_booking(self.admin, portal=portal, passenger_name=f"Passenger {i}")

    def test_a_long_report_spans_multiple_pages(self):
        content = build_pdf(TravelBooking.objects.all(), []).getvalue()
        pages = content.count(b"/Type /Page") - content.count(b"/Type /Pages")
        self.assertGreater(pages, 1)

    def test_every_page_is_numbered(self):
        content = build_pdf(TravelBooking.objects.all(), []).getvalue()
        self.assertIn(b"Page", content)
