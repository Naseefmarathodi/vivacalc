"""Local development settings. Never use these to serve real traffic."""

from .base import *  # noqa: F403
from .env import env, env_bool, env_list

DEBUG = env_bool("DEBUG", default=True)

ALLOWED_HOSTS = env_list(
    "ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]", "testserver"]
)

# Plain HTTP locally, so the HTTPS-only protections are off here and on in prod.
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Console by default so local testing never emails real people by accident.
# To send for real from dev, set this in .env:
#   EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_BACKEND = env(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)

# Per-process cache is fine for a single dev server.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "vivacalc-dev",
    }
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "{asctime} {levelname:<8} {name}: {message}", "style": "{"},
        # Audit lines are already fully formed; no prefix, so they stay
        # greppable: LOGIN: username=admin | time=2026-09-14 22:30:15
        "bare": {"format": "{message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
        "audit_console": {"class": "logging.StreamHandler", "formatter": "bare"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "vivacalc": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "vivacalc.audit": {
            "handlers": ["audit_console"], "level": "INFO", "propagate": False
        },
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}
