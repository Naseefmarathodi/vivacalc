"""Settings shared by every environment.

Never import this module directly — use ``vivacalc.settings.dev`` or
``vivacalc.settings.prod``. Anything security-sensitive defaults to the safe
value here and is relaxed only in ``dev``.
"""

from __future__ import annotations

from pathlib import Path

from .env import env, env_bool, env_int, env_list, read_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

read_dotenv(BASE_DIR / ".env")

# --- Core ------------------------------------------------------------------
# No default: a deployment without a key must fail at startup rather than
# silently run on a known one.
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env_bool("DEBUG", default=False)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "adminpanel",
    "vivapanel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "vivacalc.urls"
WSGI_APPLICATION = "vivacalc.wsgi.application"
ASGI_APPLICATION = "vivacalc.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "vivacalc.context_processors.branding",
            ],
        },
    },
]

# --- Database --------------------------------------------------------------
# DATABASE_URL (postgres://user:pass@host:port/name) takes precedence;
# otherwise fall back to the local SQLite file.
_database_url = env("DATABASE_URL", default="")
if _database_url:
    from urllib.parse import unquote, urlparse

    _parsed = urlparse(_database_url)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _parsed.path.lstrip("/"),
            "USER": unquote(_parsed.username or ""),
            "PASSWORD": unquote(_parsed.password or ""),
            "HOST": _parsed.hostname or "",
            "PORT": str(_parsed.port or ""),
            "CONN_MAX_AGE": env_int("CONN_MAX_AGE", 60),
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "adminpanel.CustomUser"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Authentication flow ---------------------------------------------------
# Without these, @login_required sends anonymous users to /accounts/login/,
# which this project does not define (it 404s).
LOGIN_URL = "vivacalc:login"
LOGIN_REDIRECT_URL = "vivacalc:post_login"
LOGOUT_REDIRECT_URL = "vivacalc:login"

# --- Login throttle --------------------------------------------------------
# Enforced by vivapanel.throttle via the cache. The cache backend must be
# shared across processes in production — see prod.py.
LOGIN_ATTEMPT_LIMIT = env_int("LOGIN_ATTEMPT_LIMIT", 5)
LOGIN_ATTEMPT_COOLOFF_MINUTES = env_int("LOGIN_ATTEMPT_COOLOFF_MINUTES", 15)

# --- Exports ---------------------------------------------------------------
# Exports are generated synchronously and held in memory; this ceiling keeps a
# single request from exhausting a worker.
EXPORT_MAX_ROWS = env_int("EXPORT_MAX_ROWS", 10_000)
BOOKINGS_PER_PAGE = env_int("BOOKINGS_PER_PAGE", 50)

# --- Internationalisation --------------------------------------------------
LANGUAGE_CODE = "en-us"
# Timestamps are stored in UTC (USE_TZ); this controls what "today" means to
# the business, which drives every default date filter in the app.
TIME_ZONE = env("TIME_ZONE", default="Asia/Kolkata")
USE_I18N = True
USE_TZ = True

CURRENCY_SYMBOL = "₹"

# --- Static & media --------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# The Viva logo, used unmodified in the UI and in both export formats.
BRAND_LOGO_PATH = BASE_DIR / "static" / "logo.png"
BRAND_NAME = "Viva Holidays"
APP_NAME = "VivaCalc"

# --- Sessions & cookies ----------------------------------------------------
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = env_int("SESSION_COOKIE_AGE", 60 * 60 * 12)
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True

# --- Security headers ------------------------------------------------------
# Safe by default; dev.py relaxes only what cannot work over plain HTTP.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# Refuse oversized request bodies outright.
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 500

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# --- Email ----------------------------------------------------------------
# Defined here (not just in prod) so the LAN deployment gets it too.
# dev.py overrides the backend to print to the console instead of sending.
EMAIL_BACKEND = env(
    "EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = env("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", default=False)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
# Google displays app passwords in groups of four ("abcd efgh ijkl mnop").
# Strip the spaces so a copy-paste of the displayed form works either way.
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="").replace(" ", "")
# Never let a slow or unreachable mail server hold a worker thread open.
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 10)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default=EMAIL_HOST_USER or "vivacalc@localhost")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# --- Sign-in / sign-out notifications --------------------------------------
# Who is told when somebody signs in or out. Comma-separated in .env.
AUTH_NOTIFY_ENABLED = env_bool("AUTH_NOTIFY_ENABLED", default=True)
AUTH_NOTIFY_RECIPIENTS = env_list("AUTH_NOTIFY_RECIPIENTS")
AUTH_NOTIFY_ON_LOGIN = env_bool("AUTH_NOTIFY_ON_LOGIN", default=True)
AUTH_NOTIFY_ON_LOGOUT = env_bool("AUTH_NOTIFY_ON_LOGOUT", default=True)
# Also send a copy to the person who signed in, at their own address.
AUTH_NOTIFY_USER_TOO = env_bool("AUTH_NOTIFY_USER_TOO", default=False)

LOG_LEVEL = env("LOG_LEVEL", default="INFO")
