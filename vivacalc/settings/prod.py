"""Production settings.

Requires DJANGO_SECRET_KEY, ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS in the
environment. Verify with:  python manage.py check --deploy
"""

from .base import *  # noqa: F403
from .base import LOG_LEVEL
from .env import env, env_bool, env_int

DEBUG = False

# --- HTTPS -----------------------------------------------------------------
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31_536_000)  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
# Set only when running behind a proxy/load balancer that terminates TLS and
# sets this header itself — otherwise a client could spoof it.
if env_bool("BEHIND_TLS_PROXY", default=True):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Cookies ---------------------------------------------------------------
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # the template's {% csrf_token %} needs no JS read,
                              # but keeping it readable avoids breaking future AJAX

# --- Static files ----------------------------------------------------------
# Hashed, compressed filenames. Serve STATIC_ROOT from nginx (or add whitenoise).
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
    },
}

# --- Cache -----------------------------------------------------------------
# The login throttle needs a cache shared by every worker process. The database
# backend gives that with no extra infrastructure:
#     python manage.py createcachetable
# Swap in Redis later by setting CACHE_URL and changing BACKEND.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": env("CACHE_TABLE", default="vivacalc_cache"),
    }
}

# --- Email -----------------------------------------------------------------
# Inherited from base.py; override here only if production differs.

# --- Logging ---------------------------------------------------------------
# Line-oriented JSON on stdout, for whatever aggregates container logs.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "vivacalc.logging_utils.JsonFormatter",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "json"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "vivacalc": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "vivacalc.audit": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
