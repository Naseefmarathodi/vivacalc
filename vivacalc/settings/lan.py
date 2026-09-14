"""Settings for serving VivaCalc on a trusted private LAN over plain HTTP.

Use this — not ``prod`` — when the app is reached as ``http://myserver.local``
from phones and PCs on the office Wi-Fi, with no TLS certificate in front.

Why a separate module rather than reusing ``prod``:

``prod`` assumes a TLS terminator. Applied to a plain-HTTP LAN it breaks the
site in three ways, two of them silently:

* ``SECURE_SSL_REDIRECT`` 301s every request to ``https://myserver.local``,
  where nothing is listening.
* ``SESSION_COOKIE_SECURE`` / ``CSRF_COOKIE_SECURE`` stop the browser sending
  those cookies over http, so sign-in appears to succeed and then does nothing.
* ``SECURE_HSTS_SECONDS`` tells every browser that touches the site to refuse
  http for ``myserver.local`` for a year. That is cached per device and is
  genuinely unpleasant to undo on a phone.

So those three are off here — deliberately, and only because the listener is
bound to a private address that is never routed from the internet. Everything
that does not depend on TLS stays on.
"""

from __future__ import annotations

from .base import *  # noqa: F403
from .base import BASE_DIR, LOG_LEVEL
from .env import env, env_bool, env_int, env_list

DEBUG = False

# --- Who may answer to this name ------------------------------------------
# The server's DHCP lease moves inside a known pool, so every address in that
# pool is accepted, alongside the mDNS name and the bare Windows hostname.
LAN_HOSTNAME = env("LAN_HOSTNAME", default="myserver.local")
LAN_SHORT_NAME = LAN_HOSTNAME.split(".")[0]

DHCP_SUBNET = env("DHCP_SUBNET", default="192.168.1")
DHCP_RANGE_START = env_int("DHCP_RANGE_START", 50)
DHCP_RANGE_END = env_int("DHCP_RANGE_END", 150)

_dhcp_pool = [
    f"{DHCP_SUBNET}.{octet}"
    for octet in range(DHCP_RANGE_START, DHCP_RANGE_END + 1)
]

ALLOWED_HOSTS = [
    LAN_HOSTNAME,          # myserver.local  — the address people type
    LAN_SHORT_NAME,        # myserver        — NetBIOS/LLMNR from Windows PCs
    "localhost",
    "127.0.0.1",
    *_dhcp_pool,           # whatever DHCP happens to have handed out today
    *env_list("EXTRA_ALLOWED_HOSTS"),
]

# Django compares the Origin header against these for unsafe methods. The
# scheme matters, so both the name and every pool address are listed as http.
CSRF_TRUSTED_ORIGINS = [
    f"http://{LAN_HOSTNAME}",
    f"http://{LAN_SHORT_NAME}",
    "http://localhost",
    "http://127.0.0.1",
    *(f"http://{host}" for host in _dhcp_pool),
    *env_list("EXTRA_CSRF_TRUSTED_ORIGINS"),
]

# --- TLS-dependent protections: off, because there is no TLS ---------------
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0          # never set this on a plain-HTTP hostname
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# --- Everything not requiring TLS stays on ---------------------------------
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# --- Static files ----------------------------------------------------------
# Waitress serves the WSGI app only; there is no nginx on the LAN box, so
# WhiteNoise handles /static/ from inside the app.
if env_bool("USE_WHITENOISE", default=True):
    MIDDLEWARE = [
        "django.middleware.security.SecurityMiddleware",
        "whitenoise.middleware.WhiteNoiseMiddleware",
        *[m for m in MIDDLEWARE if m != "django.middleware.security.SecurityMiddleware"],  # noqa: F405
    ]
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        },
    }

# --- Cache -----------------------------------------------------------------
# The login throttle must be shared across Waitress threads and any restart.
# Database-backed needs no extra service: python manage.py createcachetable
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": env("CACHE_TABLE", default="vivacalc_cache"),
    }
}

# --- Logging ---------------------------------------------------------------
# Running as a Windows Service means stdout goes nowhere, so log to a file.
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "vivacalc.logging_utils.JsonFormatter"},
        "plain": {
            "format": "{asctime} {levelname:<8} {name}: {message}", "style": "{"
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "vivacalc.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
            "formatter": "json",
        },
    },
    "root": {"handlers": ["console", "file"], "level": LOG_LEVEL},
    "loggers": {
        "vivacalc": {
            "handlers": ["console", "file"], "level": LOG_LEVEL, "propagate": False
        },
        "django.request": {
            "handlers": ["console", "file"], "level": "ERROR", "propagate": False
        },
        "django.security": {
            "handlers": ["console", "file"], "level": "WARNING", "propagate": False
        },
    },
}
