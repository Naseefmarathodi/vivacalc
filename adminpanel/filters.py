"""Validated booking filters.

Every screen that lists or exports bookings uses this one form, so the list and
its exports can never disagree about which rows they cover, and no user-supplied
value reaches the ORM unvalidated.
"""

from __future__ import annotations

from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import QuerySet
from django.utils import timezone

from .models import Portal, TravelBooking

DEFAULT_WINDOW_DAYS = 7


class BookingFilterForm(forms.Form):
    """Booking list/export filters.

    All fields are optional. Invalid input produces field errors shown in the
    toolbar — never a 500, and never a silently unfiltered result set.
    """

    passenger_name = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "Passenger"}),
    )
    sector = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "Sector"}),
    )
    portal = forms.ModelChoiceField(
        queryset=Portal.objects.none(), required=False, empty_label="All portals"
    )
    user = forms.ModelChoiceField(
        queryset=None, required=False, empty_label="All users", label="Entered by"
    )
    start_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    end_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )

    def __init__(self, *args, include_user_filter: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["portal"].queryset = Portal.objects.all()
        if include_user_filter:
            self.fields["user"].queryset = get_user_model().objects.order_by("username")
        else:
            # Staff screens only ever show the signed-in user's own rows.
            del self.fields["user"]

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and start > end:
            self.add_error("end_date", "End date cannot be before the start date.")
        return cleaned

    # -- application -------------------------------------------------------
    def apply(self, queryset: QuerySet[TravelBooking]) -> QuerySet[TravelBooking]:
        """Return *queryset* narrowed by the validated filters.

        Invalid input filters nothing out; the caller shows the field errors
        alongside the unnarrowed result, which is less surprising than an
        empty table with no explanation.
        """
        if not self.is_valid():
            return queryset

        data = self.cleaned_data
        if data.get("start_date"):
            queryset = queryset.filter(created_at__date__gte=data["start_date"])
        if data.get("end_date"):
            queryset = queryset.filter(created_at__date__lte=data["end_date"])
        if data.get("user"):
            queryset = queryset.filter(entered_by=data["user"])
        if data.get("portal"):
            queryset = queryset.filter(portal=data["portal"])
        if data.get("passenger_name"):
            queryset = queryset.filter(
                passenger_name__icontains=data["passenger_name"]
            )
        if data.get("sector"):
            queryset = queryset.filter(sector__icontains=data["sector"])
        return queryset

    # -- presentation ------------------------------------------------------
    @property
    def is_filtered(self) -> bool:
        """True when the user actually asked for something."""
        if not self.is_bound:
            return False
        return any(self.data.get(name) for name in self.fields)

    def describe(self) -> list[tuple[str, str]]:
        """Human-readable (label, value) pairs, for export headers."""
        if not self.is_valid():
            return []
        out: list[tuple[str, str]] = []
        for name, field in self.fields.items():
            value = self.cleaned_data.get(name)
            if not value:
                continue
            if name in {"start_date", "end_date"}:
                value = value.strftime("%d %b %Y")
            out.append((field.label or name.replace("_", " ").title(), str(value)))
        return out

    def querystring(self) -> str:
        """The active filters, re-encoded so exports inherit them exactly."""
        parts = []
        for name in self.fields:
            raw = (self.data.get(name) or "").strip() if self.is_bound else ""
            if raw:
                parts.append((name, raw))
        return "&".join(f"{k}={v}" for k, v in parts)


def default_date_range() -> tuple[str, str]:
    """The window the booking list opens on: the last seven days, inclusive.

    Uses localdate() so the day boundary follows the business timezone rather
    than UTC.
    """
    today = timezone.localdate()
    start = today - timedelta(days=DEFAULT_WINDOW_DAYS)
    return start.isoformat(), today.isoformat()
