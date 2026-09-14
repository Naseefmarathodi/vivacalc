"""Admin-panel views: dashboard, bookings, portals, users and exports.

Every view here is gated by :func:`panel_admin_required`. The booking list and
both exports share one :class:`BookingFilterForm`, so an export always covers
exactly the rows the list showed.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.core.paginator import Paginator
from django.db.models import Count, ProtectedError, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .exports import ExportTooLarge, build_pdf, build_workbook
from .filters import BookingFilterForm, default_date_range
from .forms import (
    AdminSetPasswordForm,
    CustomUserChangeForm,
    CustomUserCreationForm,
    PortalForm,
    TravelBookingForm,
)
from .models import Portal, TravelBooking
from .permissions import panel_admin_required

logger = logging.getLogger("vivacalc.adminpanel")

User = get_user_model()


def permission_denied(request):
    """Landing page for a signed-in user who lacks panel access."""
    return render(
        request,
        "errors/error.html",
        {
            "status_code": 403,
            "title": "Admin access required",
            "message": "This area is limited to administrators. Your account "
                       "has the Staff role.",
        },
        status=403,
    )


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
def _all_bookings():
    return TravelBooking.objects.select_related("portal", "entered_by")


@panel_admin_required
def dashboard(request):
    """Ledger-wide summary. Every figure comes from the database."""
    today = timezone.localdate()
    week_start = today - timedelta(days=6)
    month_start = today.replace(day=1)

    bookings = TravelBooking.objects.all()

    def window(qs):
        return qs.aggregate(
            count=Count("id"),
            total_buy=Sum("buy_price"),
            total_sell=Sum("sell_price"),
            total_margin=Sum("margin"),
        )

    context = {
        "page_title": "Dashboard",
        "overall": window(bookings),
        "today_stats": window(bookings.filter(created_at__date=today)),
        "week_stats": window(bookings.filter(created_at__date__gte=week_start)),
        "month_stats": window(bookings.filter(created_at__date__gte=month_start)),
        "recent_bookings": _all_bookings()[:8],
        "active_portals": Portal.objects.filter(is_active=True).count(),
        "total_portals": Portal.objects.count(),
        "staff_count": User.objects.filter(is_active=True).count(),
        "top_users": (
            _all_bookings()
            .values("entered_by__username")
            .annotate(count=Count("id"), margin=Sum("margin"))
            .order_by("-margin")[:5]
        ),
        "today": today,
    }
    return render(request, "panel/dashboard.html", context)


# --------------------------------------------------------------------------
# Bookings
# --------------------------------------------------------------------------
def _bound_filter_form(request) -> BookingFilterForm:
    """Bind the filter form, defaulting to the last seven days on first load."""
    if request.GET:
        return BookingFilterForm(request.GET)
    start, end = default_date_range()
    return BookingFilterForm({"start_date": start, "end_date": end})


@panel_admin_required
def booking_list(request):
    form = _bound_filter_form(request)
    bookings = form.apply(_all_bookings())

    totals = bookings.aggregate(
        total_buy=Sum("buy_price"),
        total_sell=Sum("sell_price"),
        total_margin=Sum("margin"),
    )
    paginator = Paginator(bookings, settings.BOOKINGS_PER_PAGE)
    page = paginator.get_page(request.GET.get("page"))

    context = {
        "page_title": "Bookings",
        "filter_form": form,
        "page_obj": page,
        "bookings": page.object_list,
        "totals": totals,
        "result_count": paginator.count,
        # Carried into the export links so they cover the same rows.
        "filter_query": form.querystring(),
    }
    return render(request, "panel/booking_list.html", context)


@panel_admin_required
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
            return redirect("adminpanel:booking_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = TravelBookingForm()
    return render(
        request,
        "panel/booking_form.html",
        {"form": form, "page_title": "New booking", "is_edit": False},
    )


@panel_admin_required
def booking_update(request, pk):
    booking = get_object_or_404(_all_bookings(), pk=pk)
    if request.method == "POST":
        form = TravelBookingForm(request.POST, instance=booking)
        if form.is_valid():
            form.save()
            messages.success(
                request, f"Booking for {booking.passenger_name} updated successfully."
            )
            return redirect("adminpanel:booking_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = TravelBookingForm(instance=booking)
    return render(
        request,
        "panel/booking_form.html",
        {
            "form": form,
            "booking": booking,
            "page_title": "Edit booking",
            "is_edit": True,
        },
    )


@panel_admin_required
def booking_delete(request, pk):
    booking = get_object_or_404(_all_bookings(), pk=pk)
    if request.method == "POST":
        name = booking.passenger_name
        booking.delete()
        logger.info(
            "booking deleted",
            extra={"booking_id": pk, "actor_id": request.user.pk},
        )
        messages.success(request, f"Booking for {name} deleted successfully.")
        return redirect("adminpanel:booking_list")
    return render(
        request,
        "panel/booking_confirm_delete.html",
        {"booking": booking, "page_title": "Delete booking"},
    )


# --------------------------------------------------------------------------
# Exports — same filter form as the list above
# --------------------------------------------------------------------------
def _export_queryset(request):
    form = _bound_filter_form(request)
    return form, form.apply(_all_bookings())


def _timestamped(prefix: str, extension: str) -> str:
    return f"{prefix}-{timezone.localtime():%Y%m%d-%H%M}.{extension}"


@panel_admin_required
def export_bookings_excel(request):
    form, bookings = _export_queryset(request)
    try:
        stream = build_workbook(bookings, form.describe())
    except ExportTooLarge as exc:
        messages.error(request, f"{exc} Narrow the date range and try again.")
        return redirect("adminpanel:booking_list")
    except Exception:
        logger.exception("excel export failed", extra={"actor_id": request.user.pk})
        messages.error(request, "The Excel export could not be generated.")
        return redirect("adminpanel:booking_list")

    response = HttpResponse(
        stream.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument."
                     "spreadsheetml.sheet",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="{_timestamped("vivacalc-bookings", "xlsx")}"'
    )
    logger.info("excel export", extra={"actor_id": request.user.pk})
    return response


@panel_admin_required
def export_bookings_pdf(request):
    form, bookings = _export_queryset(request)
    try:
        stream = build_pdf(bookings, form.describe())
    except ExportTooLarge as exc:
        messages.error(request, f"{exc} Narrow the date range and try again.")
        return redirect("adminpanel:booking_list")
    except Exception:
        logger.exception("pdf export failed", extra={"actor_id": request.user.pk})
        messages.error(request, "The PDF export could not be generated.")
        return redirect("adminpanel:booking_list")

    response = HttpResponse(stream.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="{_timestamped("vivacalc-bookings", "pdf")}"'
    )
    logger.info("pdf export", extra={"actor_id": request.user.pk})
    return response


# --------------------------------------------------------------------------
# Portals
# --------------------------------------------------------------------------
@panel_admin_required
def portal_list(request):
    portals = Portal.objects.annotate(bookings_total=Count("bookings"))
    return render(
        request,
        "panel/portal_list.html",
        {"portals": portals, "page_title": "Portals"},
    )


@panel_admin_required
def portal_create(request):
    if request.method == "POST":
        form = PortalForm(request.POST)
        if form.is_valid():
            portal = form.save()
            messages.success(request, f"Portal {portal.name} created successfully.")
            return redirect("adminpanel:portal_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = PortalForm()
    return render(
        request,
        "panel/portal_form.html",
        {"form": form, "page_title": "New portal", "is_edit": False},
    )


@panel_admin_required
def portal_update(request, pk):
    portal = get_object_or_404(Portal, pk=pk)
    if request.method == "POST":
        form = PortalForm(request.POST, instance=portal)
        if form.is_valid():
            form.save()
            messages.success(request, f"Portal {portal.name} updated successfully.")
            return redirect("adminpanel:portal_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = PortalForm(instance=portal)
    return render(
        request,
        "panel/portal_form.html",
        {"form": form, "portal": portal, "page_title": "Edit portal", "is_edit": True},
    )


@panel_admin_required
def portal_delete(request, pk):
    """Delete a portal only when it carries no history.

    A portal with bookings is never removed — the admin is directed to mark it
    inactive instead, which keeps every historical booking intact.
    """
    portal = get_object_or_404(Portal, pk=pk)
    in_use = portal.bookings.count()

    if request.method == "POST":
        if in_use:
            messages.error(
                request,
                f"{portal.name} is used by {in_use} booking(s) and cannot be "
                "deleted. Mark it inactive instead to keep the history.",
            )
            return redirect("adminpanel:portal_list")
        try:
            portal.delete()
        except ProtectedError:
            messages.error(
                request,
                f"{portal.name} still has bookings attached and cannot be deleted.",
            )
            return redirect("adminpanel:portal_list")
        messages.success(request, f"Portal {portal.name} deleted successfully.")
        return redirect("adminpanel:portal_list")

    return render(
        request,
        "panel/portal_confirm_delete.html",
        {"portal": portal, "in_use": in_use, "page_title": "Delete portal"},
    )


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------
@panel_admin_required
def user_list(request):
    users = User.objects.annotate(bookings_total=Count("travel_entries"))
    return render(
        request, "panel/user_list.html", {"users": users, "page_title": "Users"}
    )


@panel_admin_required
def user_create(request):
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            created = form.save()
            logger.info(
                "user created",
                extra={"new_user_id": created.pk, "actor_id": request.user.pk},
            )
            messages.success(request, f"User {created.username} created successfully.")
            return redirect("adminpanel:user_list")
        messages.error(request, "Please correct the errors below.")
    else:
        form = CustomUserCreationForm()
    return render(
        request,
        "panel/user_form.html",
        {"form": form, "page_title": "New user", "is_edit": False},
    )


def _render_user_form(request, target_user, form=None, password_form=None):
    """Render the edit page with both forms.

    The profile form and the password form post to different endpoints, so
    whichever one did not just fail validation is rebuilt unbound.
    """
    return render(
        request,
        "panel/user_form.html",
        {
            "form": form or CustomUserChangeForm(instance=target_user),
            "password_form": password_form or AdminSetPasswordForm(target_user),
            "target_user": target_user,
            "page_title": "Edit user",
            "is_edit": True,
        },
    )


def _self_lockout_reason(actor, target, cleaned) -> str | None:
    """Why *actor* may not apply this change to *target*, or None.

    Guards the one edit that cannot be undone from inside the app: an admin
    removing their own access. Once saved they could not reach this page to
    put it back.
    """
    if actor.pk != target.pk:
        return None
    if not cleaned.get("is_active", True):
        return "You cannot deactivate your own account."
    if cleaned.get("role") != User.Role.ADMIN and not target.is_superuser:
        return (
            "You cannot remove your own Admin role — you would lose access to "
            "this page. Ask another administrator to change it."
        )
    return None


@panel_admin_required
def user_update(request, pk):
    # Named target_user, not user: `user` would shadow request.user in templates.
    target_user = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = CustomUserChangeForm(request.POST, instance=target_user)
        if form.is_valid():
            blocked = _self_lockout_reason(
                request.user, target_user, form.cleaned_data
            )
            if blocked:
                messages.error(request, blocked)
                return _render_user_form(request, target_user, form=form)
            form.save()
            messages.success(
                request, f"User {target_user.username} updated successfully."
            )
            return redirect("adminpanel:user_list")
        messages.error(request, "Please correct the errors below.")
        return _render_user_form(request, target_user, form=form)
    return _render_user_form(request, target_user)


@panel_admin_required
@require_http_methods(["POST"])
def user_set_password(request, pk):
    """Set a new password for *pk*.

    An administrator does not need the old password — and could not supply it
    anyway, since stored passwords are one-way hashes. Django's validators
    (including this project's 10-character minimum) still apply.
    """
    target_user = get_object_or_404(User, pk=pk)
    password_form = AdminSetPasswordForm(target_user, request.POST)

    if not password_form.is_valid():
        messages.error(request, "The new password was not accepted.")
        return _render_user_form(request, target_user, password_form=password_form)

    password_form.save()
    logger.info(
        "password reset by administrator",
        extra={"target_user_id": target_user.pk, "actor_id": request.user.pk},
    )

    if target_user.pk == request.user.pk:
        # Changing your own password rotates the session hash; without this the
        # admin who just used this form would be signed out immediately.
        update_session_auth_hash(request, target_user)
        messages.success(request, "Your password was changed successfully.")
    else:
        messages.success(
            request,
            f"Password updated for {target_user.username}. Share it with them "
            "over a trusted channel — it cannot be looked up again.",
        )
    return redirect("adminpanel:user_update", pk=target_user.pk)


def _blocking_reason(actor, target) -> str | None:
    """Why *target* may not be deleted by *actor*, or None if deletion is fine."""
    if actor.pk == target.pk:
        return "You cannot delete your own account."
    if target.is_panel_admin:
        remaining = (
            User.objects.filter(Q(is_superuser=True) | Q(role=User.Role.ADMIN))
            .exclude(pk=target.pk)
            .filter(is_active=True)
            .count()
        )
        if remaining == 0:
            return (
                "This is the last administrator. Promote another user first, "
                "otherwise nobody could administer VivaCalc."
            )
    return None


@panel_admin_required
def user_delete(request, pk):
    target_user = get_object_or_404(User, pk=pk)
    blocked = _blocking_reason(request.user, target_user)
    booking_count = target_user.travel_entries.count()

    if request.method == "POST":
        if blocked:
            messages.error(request, blocked)
            return redirect("adminpanel:user_list")
        username = target_user.username
        target_user.delete()
        logger.info(
            "user deleted", extra={"deleted_user": username, "actor_id": request.user.pk}
        )
        messages.success(
            request,
            f"User {username} deleted successfully. Their bookings were kept.",
        )
        return redirect("adminpanel:user_list")

    return render(
        request,
        "panel/user_confirm_delete.html",
        {
            "target_user": target_user,
            "blocked": blocked,
            "booking_count": booking_count,
            "page_title": "Delete user",
        },
    )
