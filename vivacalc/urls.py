"""Root URL configuration."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from vivapanel.views import healthz

urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path("django-admin/", admin.site.urls),
    path("adminpanel/", include("adminpanel.urls")),
    path("", include("vivapanel.urls")),
]

# Custom error handlers (used when DEBUG is False).
handler403 = "vivacalc.errors.permission_denied"
handler404 = "vivacalc.errors.page_not_found"
handler500 = "vivacalc.errors.server_error"

if settings.DEBUG:
    # Dev-only convenience; production serves these from the web server.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
