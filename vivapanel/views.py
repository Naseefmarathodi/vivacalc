"""Staff-facing views: sign-in, personal dashboard and own-booking CRUD.

Every booking view here is scoped to ``entered_by=request.user``. That scoping
is the application's core access control and must not be relaxed.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from adminpanel.filters import BookingFilterForm
from adminpanel.forms import TravelBookingForm
from adminpanel.models import TravelBooking

from . import throttle

logger = logging.getLogger("vivacalc.auth")

ZERO_TOTALS = {"total_buy": None, "total_sell": None, "total_margin": None}


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------
class ThrottledLoginView(auth_views.LoginView):
    """The single sign-in entry point for the whole application.

    Django's LoginView and AuthenticationForm do the authentication; this
    subclass only adds the attempt throttle and the audit log line.
    """

    template_name = "auth/login.html"
    redirect_authenticated_user = True
    form_class = AuthenticationForm

    def dispatch(self, request, *args, **kwargs):
        self.client_ip = throttle.client_ip(request)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        username = (request.POST.get("username") or "").strip()
        if throttle.is_locked_out(username, self.client_ip):
            logger.warning(
                "login blocked by throttle",
                extra={"username": username, "client_ip": self.client_ip},
            )
            form = self.get_form()
            form.add_error(
                None,
                "Too many failed sign-in attempts. Please try again in "
                f"{settings.LOGIN_ATTEMPT_COOLOFF_MINUTES} minutes.",
            )
            return self.render_to_response(self.get_context_data(form=form, locked=True))
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        throttle.reset(form.get_user().get_username(), self.client_ip)
        logger.info(
            "login succeeded",
            extra={"user_id": form.get_user().pk, "client_ip": self.client_ip},
        )
        return super().form_valid(form)

    def form_invalid(self, form):
        username = (self.request.POST.get("username") or "").strip()
        remaining = throttle.attempts_remaining(username, self.client_ip)
        throttle.record_failure(username, self.client_ip)
        if 0 < remaining <= 3:
            form.add_error(
                None, f"{remaining} attempt(s) remaining before a temporary lockout."
            )
        return super().form_invalid(form)


@login_required
def post_login_router(request):
    """Send each user to the dashboard that matches their role."""
    if request.user.is_panel_admin:
        return redirect("adminpanel:dashboard")
    return redirect("vivacalc:dashboard")


class PostOnlyLogoutView(auth_views.LogoutView):
    """Logout is POST-only (Django's default since 5.0); a GET explains why."""

    next_page = reverse_lazy("vivacalc:login")

    def get(self, request, *args, **kwargs):
        return render(request, "auth/logout_confirm.html", status=405)


# --------------------------------------------------------------------------
# Staff dashboard
# --------------------------------------------------------------------------
def _own_bookings(user):
    return TravelBooking.objects.filter(entered_by=user).select_related(
        "portal", "entered_by"
    )


@login_required
def dashboard(request):
    """Personal summary: the signed-in user's own figures only."""
    today = timezone.localdate()
    month_start = today.replace(day=1)

    mine = _own_bookings(request.user)
    totals = mine.aggregate(
        count=Count("id"),
        total_buy=Sum("buy_price"),
        total_sell=Sum("sell_price"),
        total_margin=Sum("margin"),
    )
    today_stats = mine.filter(created_at__date=today).aggregate(
        count=Count("id"), total_margin=Sum("margin")
    )
    month_stats = mine.filter(created_at__date__gte=month_start).aggregate(
        count=Count("id"), total_margin=Sum("margin")
    )

    context = {
        "page_title": "Dashboard",
        "totals": totals,
        "today_stats": today_stats,
        "month_stats": month_stats,
        "recent_bookings": mine[:8],
        "today": today,
    }
    return render(request, "staff/dashboard.html", context)


@login_required
def booking_list(request):
    """The signed-in user's bookings, filtered and paginated."""
    form = BookingFilterForm(request.GET or None, include_user_filter=False)
    bookings = form.apply(_own_bookings(request.user))

    totals = bookings.aggregate(
        total_buy=Sum("buy_price"),
        total_sell=Sum("sell_price"),
        total_margin=Sum("margin"),
    )
    paginator = Paginator(bookings, settings.BOOKINGS_PER_PAGE)
    page = paginator.get_page(request.GET.get("page"))

    context = {
        "page_title": "My bookings",
        "filter_form": form,
        "page_obj": page,
        "bookings": page.object_list,
        "totals": totals,
        "result_count": paginator.count,
        "filter_query": form.querystring(),
    }
    return render(request, "staff/booking_list.html", context)


@login_required
def booking_create(request):
    if request.method == "POST":
        form = TravelBookingForm(request.POST)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.entered_by = request.user
            booking.save()
            messages.success(
                request, f"Booking for {booking.passenger_name} created successfully."
            )
            return redirect("vivacalc:booking_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = TravelBookingForm()
    return render(
        request,
        "staff/booking_form.html",
        {"form": form, "page_title": "New booking", "is_edit": False},
    )


@login_required
def booking_update(request, pk):
    # Ownership scoping — a staff user may only reach their own bookings.
    booking = get_object_or_404(TravelBooking, pk=pk, entered_by=request.user)
    if request.method == "POST":
        form = TravelBookingForm(request.POST, instance=booking)
        if form.is_valid():
            form.save()
            messages.success(
                request, f"Booking for {booking.passenger_name} updated successfully."
            )
            return redirect("vivacalc:booking_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = TravelBookingForm(instance=booking)
    return render(
        request,
        "staff/booking_form.html",
        {
            "form": form,
            "booking": booking,
            "page_title": "Edit booking",
            "is_edit": True,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def booking_delete(request, pk):
    booking = get_object_or_404(TravelBooking, pk=pk, entered_by=request.user)
    if request.method == "POST":
        name = booking.passenger_name
        booking.delete()
        messages.success(request, f"Booking for {name} deleted successfully.")
        return redirect("vivacalc:booking_list")
    return render(
        request,
        "staff/booking_confirm_delete.html",
        {"booking": booking, "page_title": "Delete booking"},
    )


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------
def healthz(request) -> HttpResponse:
    """Liveness/readiness probe. 200 when the database answers."""
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        logger.exception("health check failed")
        return HttpResponse("unhealthy\n", status=503, content_type="text/plain")
    return HttpResponse("ok\n", status=200, content_type="text/plain")
