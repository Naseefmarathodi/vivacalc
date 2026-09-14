"""Domain models for the VivaCalc booking ledger."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q


class CustomUser(AbstractUser):
    """Application user.

    ``role`` is the authoritative application permission: it decides who may
    reach the admin panel. ``is_superuser`` is kept for the Django admin site
    only, and always implies panel access.
    """

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        STAFF = "staff", "Staff"

    phone = models.CharField(max_length=15, unique=True, blank=True, null=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STAFF)

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"
        ordering = ("username",)

    def __str__(self) -> str:
        return f"{self.username} ({self.get_role_display()})"

    @property
    def is_panel_admin(self) -> bool:
        """True when this user may use the admin panel."""
        return self.is_superuser or self.role == self.Role.ADMIN

    @property
    def display_name(self) -> str:
        return self.get_full_name() or self.username


class Portal(models.Model):
    """A supplier / booking portal that bookings are sold through."""

    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive portals stay on historical bookings but cannot be "
                  "chosen for new ones.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name

    @property
    def booking_count(self) -> int:
        return self.bookings.count()


class TravelBooking(models.Model):
    """A single sale: what was bought from a portal and sold to a passenger.

    ``margin`` is derived, never entered: it is computed in :meth:`save` from
    two Decimals and is not exposed on any form.

    A database CHECK enforcing ``margin == sell_price - buy_price`` was tried
    and removed. SQLite has no true decimal type — DecimalField lands in a
    float-backed NUMERIC column — so the check rejects honest rows:
    ``0.30 - 0.10`` evaluates to ``0.19999999999999998`` there. The rule is
    therefore enforced in :meth:`save` and covered by tests. On PostgreSQL,
    whose NUMERIC arithmetic is exact, the constraint can be reinstated.
    """

    passenger_name = models.CharField(max_length=200)
    sector = models.TextField(blank=True)
    service = models.TextField()
    portal = models.ForeignKey(
        Portal,
        # PROTECT: retiring a supplier must never destroy its sales history.
        on_delete=models.PROTECT,
        related_name="bookings",
        blank=True,
        null=True,
    )
    buy_price = models.DecimalField(max_digits=10, decimal_places=2)
    sell_price = models.DecimalField(max_digits=10, decimal_places=2)
    margin = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="travel_entries",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=["entered_by", "-created_at"], name="booking_owner_recent_idx"
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(buy_price__gte=Decimal("0"))
                & Q(sell_price__gte=Decimal("0")),
                name="booking_prices_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.passenger_name} - {self.sector} ({self.portal})"

    def save(self, *args, **kwargs):
        self.margin = self.compute_margin()
        super().save(*args, **kwargs)

    def compute_margin(self) -> Decimal:
        """margin = sell_price - buy_price, in Decimal throughout."""
        buy = self.buy_price if self.buy_price is not None else Decimal("0")
        sell = self.sell_price if self.sell_price is not None else Decimal("0")
        return Decimal(sell) - Decimal(buy)
