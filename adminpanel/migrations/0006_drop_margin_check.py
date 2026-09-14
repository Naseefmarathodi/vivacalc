"""Remove the margin equality CHECK constraint added in 0004.

The constraint was ``margin == sell_price - buy_price``. It is correct in
principle but not portable: SQLite has no decimal type, so DecimalField values
live in a float-backed NUMERIC column and the database evaluates
``0.30 - 0.10`` as ``0.19999999999999998``. The constraint therefore rejected
legitimate bookings priced in paise.

The rule still holds — TravelBooking.save() computes margin in Decimal, and the
test suite asserts it, including fractional cases. On PostgreSQL (exact NUMERIC
arithmetic) this constraint can be reinstated.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("adminpanel", "0005_backfill_superuser_roles"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="travelbooking",
            name="booking_margin_matches_prices",
        ),
    ]
