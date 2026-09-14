"""Django-admin registrations (a fallback tool; the panel is the main UI)."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import CustomUserCreationForm
from .models import CustomUser, Portal, TravelBooking


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    model = CustomUser
    list_display = ("username", "email", "phone", "role", "is_active", "is_superuser")
    list_filter = ("role", "is_active", "is_superuser")
    search_fields = ("username", "email", "phone")
    ordering = ("username",)
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal", {"fields": ("first_name", "last_name", "email", "phone")}),
        ("Permissions", {
            "fields": ("role", "is_active", "is_staff", "is_superuser",
                       "groups", "user_permissions"),
        }),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "email", "phone", "role",
                       "password1", "password2", "is_active"),
        }),
    )


@admin.register(Portal)
class PortalAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(TravelBooking)
class TravelBookingAdmin(admin.ModelAdmin):
    list_display = ("passenger_name", "sector", "portal", "service", "buy_price",
                    "sell_price", "margin", "entered_by", "created_at")
    list_filter = ("portal", "entered_by", "created_at")
    search_fields = ("passenger_name", "sector", "service")
    readonly_fields = ("margin", "created_at", "updated_at")
    list_select_related = ("portal", "entered_by")
    date_hierarchy = "created_at"
