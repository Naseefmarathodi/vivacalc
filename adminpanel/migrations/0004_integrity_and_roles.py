"""Data-integrity and permission-model migration.

Hand-written rather than generated so the operation order is explicit: the
CHECK constraints are added last, after every column they reference exists.

Verified against the existing database before writing: 0 rows violate
margin == sell_price - buy_price and 0 rows have a negative price, so both
constraints apply without a data fix-up.
"""

import django.db.models.deletion
import django.utils.timezone
from decimal import Decimal
from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):

    dependencies = [
        ("adminpanel", "0003_alter_travelbooking_portal"),
    ]

    operations = [
        # --- UserProfile: duplicated phone/role from CustomUser, 0 rows,
        # referenced nowhere in code or templates. Removed.
        migrations.DeleteModel(name="UserProfile"),

        # --- CustomUser -----------------------------------------------------
        migrations.AlterModelOptions(
            name="customuser",
            options={
                "ordering": ("username",),
                "verbose_name": "user",
                "verbose_name_plural": "users",
            },
        ),
        migrations.AlterField(
            model_name="customuser",
            name="role",
            field=models.CharField(
                choices=[("admin", "Admin"), ("staff", "Staff")],
                default="staff",
                max_length=20,
            ),
        ),

        # --- Portal ---------------------------------------------------------
        migrations.AlterModelOptions(name="portal", options={"ordering": ("name",)}),
        migrations.AddField(
            model_name="portal",
            name="is_active",
            field=models.BooleanField(
                default=True,
                help_text="Inactive portals stay on historical bookings but "
                          "cannot be chosen for new ones.",
            ),
        ),
        migrations.AddField(
            model_name="portal",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True, default=django.utils.timezone.now
            ),
            preserve_default=False,
        ),

        # --- TravelBooking --------------------------------------------------
        migrations.AlterModelOptions(
            name="travelbooking", options={"ordering": ("-created_at",)}
        ),
        migrations.AlterField(
            model_name="travelbooking",
            name="portal",
            field=models.ForeignKey(
                blank=True,
                null=True,
                # PROTECT: deleting a supplier must not delete its sales history.
                on_delete=django.db.models.deletion.PROTECT,
                related_name="bookings",
                to="adminpanel.portal",
            ),
        ),
        migrations.AlterField(
            model_name="travelbooking",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
        migrations.AddField(
            model_name="travelbooking",
            name="updated_at",
            field=models.DateTimeField(
                auto_now=True, default=django.utils.timezone.now
            ),
            preserve_default=False,
        ),
        migrations.AddIndex(
            model_name="travelbooking",
            index=models.Index(
                fields=["entered_by", "-created_at"], name="booking_owner_recent_idx"
            ),
        ),

        # --- Constraints last, once every referenced column exists -----------
        migrations.AddConstraint(
            model_name="travelbooking",
            constraint=models.CheckConstraint(
                condition=Q(buy_price__gte=Decimal("0"))
                & Q(sell_price__gte=Decimal("0")),
                name="booking_prices_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="travelbooking",
            constraint=models.CheckConstraint(
                condition=Q(margin=F("sell_price") - F("buy_price")),
                name="booking_margin_matches_prices",
            ),
        ),
    ]
