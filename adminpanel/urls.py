"""Admin-panel routes. Every view is gated by panel_admin_required."""

from django.urls import path

from . import views

app_name = "adminpanel"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("access-denied/", views.permission_denied, name="permission_denied_page"),

    path("bookings/", views.booking_list, name="booking_list"),
    path("bookings/new/", views.booking_create, name="booking_create"),
    path("bookings/<int:pk>/edit/", views.booking_update, name="booking_update"),
    path("bookings/<int:pk>/delete/", views.booking_delete, name="booking_delete"),
    path("bookings/export/excel/", views.export_bookings_excel,
         name="export_bookings_excel"),
    path("bookings/export/pdf/", views.export_bookings_pdf,
         name="export_bookings_pdf"),

    path("portals/", views.portal_list, name="portal_list"),
    path("portals/new/", views.portal_create, name="portal_create"),
    path("portals/<int:pk>/edit/", views.portal_update, name="portal_update"),
    path("portals/<int:pk>/delete/", views.portal_delete, name="portal_delete"),

    path("users/", views.user_list, name="user_list"),
    path("users/new/", views.user_create, name="user_create"),
    path("users/<int:pk>/edit/", views.user_update, name="user_update"),
    path("users/<int:pk>/set-password/", views.user_set_password,
         name="user_set_password"),
    path("users/<int:pk>/delete/", views.user_delete, name="user_delete"),
]
