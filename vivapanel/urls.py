"""Staff-facing routes, plus the shared authentication entry points."""

from django.urls import path

from . import views

app_name = "vivacalc"

urlpatterns = [
    # Authentication — one login flow for every user.
    path("", views.ThrottledLoginView.as_view(), name="login"),
    path("logout/", views.PostOnlyLogoutView.as_view(), name="logout"),
    path("welcome/", views.post_login_router, name="post_login"),

    # Staff workspace
    path("dashboard/", views.dashboard, name="dashboard"),
    path("bookings/", views.booking_list, name="booking_list"),
    path("bookings/new/", views.booking_create, name="booking_create"),
    path("bookings/<int:pk>/edit/", views.booking_update, name="booking_update"),
    path("bookings/<int:pk>/delete/", views.booking_delete, name="booking_delete"),
]
