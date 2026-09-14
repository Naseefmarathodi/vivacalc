"""Forms for bookings, portals and users."""

from __future__ import annotations

from decimal import Decimal

from django import forms
from django.contrib.auth.forms import (
    SetPasswordForm,
    UserChangeForm,
    UserCreationForm,
)
from django.db.models import Q

from .models import CustomUser, Portal, TravelBooking


class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = ("username", "first_name", "last_name", "email", "phone", "role")


class CustomUserChangeForm(UserChangeForm):
    """Edit a user without touching their password hash.

    Deliberately excludes is_superuser / is_staff / user_permissions: panel
    admins manage application roles, not Django-admin privileges.
    """

    password = None  # UserChangeForm's read-only hash widget is not wanted here

    class Meta:
        model = CustomUser
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "phone",
            "role",
            "is_active",
        )


class AdminSetPasswordForm(SetPasswordForm):
    """Lets an administrator set a new password for another account.

    Subclasses Django's SetPasswordForm, so it requires no knowledge of the
    existing password — which is just as well, because there isn't any to
    know. Passwords are stored as one-way PBKDF2-SHA256 hashes and cannot be
    read back, by this form or anything else.

    The project's password validators (including the 10-character minimum)
    apply here, because the form runs them.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].label = "New password"
        self.fields["new_password2"].label = "Confirm new password"
        for field in self.fields.values():
            field.widget.attrs.setdefault("autocomplete", "new-password")


class TravelBookingForm(forms.ModelForm):
    """Create / edit a booking.

    ``margin`` is absent by design: it is derived from the two prices by the
    model, so there is no way to enter an inconsistent value.
    """

    class Meta:
        model = TravelBooking
        fields = ["passenger_name", "service", "sector", "portal",
                  "buy_price", "sell_price"]
        widgets = {
            "passenger_name": forms.TextInput(
                attrs={"placeholder": "e.g. Rahul Menon", "autofocus": True}
            ),
            "sector": forms.Textarea(
                attrs={"rows": 2, "placeholder": "e.g. DXB → BOM → DXB"}
            ),
            "service": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Ticket, visa, hotel, package…"}
            ),
            "buy_price": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "sell_price": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }
        labels = {
            "passenger_name": "Passenger name",
            "buy_price": "Buy price",
            "sell_price": "Sell price",
        }
        help_texts = {
            "portal": "Supplier this booking was purchased through.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Retired suppliers stay on their historical bookings but must not be
        # selectable for new ones. When editing a booking that already points
        # at a retired portal, keep that option available so saving the form
        # does not silently clear it.
        selectable = Q(is_active=True)
        if self.instance.pk and self.instance.portal_id:
            selectable |= Q(pk=self.instance.portal_id)
        self.fields["portal"].queryset = Portal.objects.filter(selectable)
        self.fields["portal"].empty_label = "— No portal —"

    def _clean_price(self, field: str) -> Decimal:
        value = self.cleaned_data.get(field)
        if value is None:
            return value
        if value < Decimal("0"):
            raise forms.ValidationError("Price cannot be negative.")
        return value

    def clean_buy_price(self):
        return self._clean_price("buy_price")

    def clean_sell_price(self):
        return self._clean_price("sell_price")

    @property
    def projected_margin(self) -> Decimal | None:
        """Margin implied by the submitted prices, for the form summary."""
        buy = self.data.get("buy_price") or (
            self.instance.buy_price if self.instance.pk else None
        )
        sell = self.data.get("sell_price") or (
            self.instance.sell_price if self.instance.pk else None
        )
        try:
            return Decimal(str(sell)) - Decimal(str(buy))
        except (TypeError, ValueError, ArithmeticError):
            return None


class PortalForm(forms.ModelForm):
    class Meta:
        model = Portal
        fields = ["name", "is_active"]
        widgets = {
            "name": forms.TextInput(
                attrs={"placeholder": "e.g. Galileo", "autofocus": True}
            ),
        }
        labels = {"is_active": "Active"}
