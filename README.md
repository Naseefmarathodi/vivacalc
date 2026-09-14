# VivaCalc

**Travel Booking Margin Ledger — Viva Holidays**

VivaCalc records travel bookings and tracks the margin on each one. Staff enter
their own bookings; administrators see the whole ledger, manage users and
suppliers, and export the ledger to Excel or PDF.

The single business rule is:

```
margin = sell_price - buy_price
```

It is computed by the server from two `Decimal` values, is never entered by
hand, and is never exposed as a form field.

---

## Features

- **Staff workspace** — personal dashboard, own-booking create/edit/delete, and
  a filtered, paginated list of your own entries.
- **Admin panel** — ledger-wide dashboard, all bookings, user management,
  supplier (portal) management.
- **Filtering** — passenger, sector, portal, user and date range, validated by
  one shared form. Invalid input produces field errors, never a 500.
- **Exports** — Excel (`.xlsx`) and multi-page PDF, both carrying the Viva logo
  and both covering *exactly* the rows the on-screen list showed.
- **Object-level security** — a staff user can only ever see or change their
  own bookings.
- **Financial-history protection** — deleting a supplier can never delete the
  bookings sold through it.

---

## Technology stack

| Component | Version | Notes |
|---|---|---|
| Python | 3.14.6 | |
| Django | 6.0.5 | |
| openpyxl | 3.1.5 | Excel export |
| reportlab | 4.5.1 | PDF export |
| Pillow | 12.2.0 | Required by both exporters to embed the logo |
| Database | SQLite (dev) / PostgreSQL or MySQL (prod) | Set `DATABASE_URL`; see docs/ |

No frontend build step. CSS and JavaScript are plain files under `static/`.
There is no API framework — the app is server-rendered, and does not need one.

---

## Requirements

- Python 3.12 or newer (verified on 3.14.6)
- PostgreSQL 13+ for production (SQLite is fine for local development)

---

## Installation

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
# paste the result into .env as DJANGO_SECRET_KEY

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open <http://127.0.0.1:8000/>.

---

## Environment variables

`.env` is read at startup and is **gitignored** — never commit it.
`DJANGO_SECRET_KEY` has no default: a misconfigured deployment fails loudly
instead of silently running on a known key.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DJANGO_SECRET_KEY` | **yes** | — | Signs sessions and CSRF tokens |
| `DJANGO_SETTINGS_MODULE` | yes | `vivacalc.settings.dev` | Which settings module to load |
| `DEBUG` | no | `False` (`True` in dev) | Never `True` in production |
| `ALLOWED_HOSTS` | prod | empty | Comma-separated hostnames |
| `CSRF_TRUSTED_ORIGINS` | prod | empty | Comma-separated `https://…` origins |
| `DATABASE_URL` | no | SQLite file | `postgres://user:pass@host:5432/name` |
| `TIME_ZONE` | no | `Asia/Kolkata` | Decides what "today" means to the business |
| `LOGIN_ATTEMPT_LIMIT` | no | `5` | Failures before a temporary lockout |
| `LOGIN_ATTEMPT_COOLOFF_MINUTES` | no | `15` | Lockout duration |
| `EXPORT_MAX_ROWS` | no | `10000` | Largest single export |
| `BOOKINGS_PER_PAGE` | no | `50` | List page size |
| `LOG_LEVEL` | no | `INFO` | Root log level |
| `SECURE_SSL_REDIRECT` | no | `True` in prod | Set `False` only if TLS terminates elsewhere |
| `BEHIND_TLS_PROXY` | no | `True` in prod | Trust `X-Forwarded-Proto` |
| `EMAIL_*` | no | — | SMTP settings |

---

## Database setup

```bash
python manage.py migrate
```

Migrations are committed and must stay committed. The notable ones:

| Migration | What it does |
|---|---|
| `0004_integrity_and_roles` | `PROTECT` on the portal FK, non-negative price constraint, `created_at` index, composite `(entered_by, -created_at)` index, `Portal.is_active`, `updated_at`, drops the unused `UserProfile` |
| `0005_backfill_superuser_roles` | Promotes existing superusers to `role="admin"` so the displayed role matches actual access |
| `0006_drop_margin_check` | Removes a `margin == sell - buy` CHECK that is not portable to SQLite (see *Known limitations*) |

### Creating an administrator

```bash
python manage.py createsuperuser
```

A superuser always has panel access. To make an ordinary account an
administrator, set its **Role** to *Admin* in the Users screen.

---

## Running locally

```bash
python manage.py runserver
```

## Running tests

```bash
python manage.py test
```

99 tests covering authentication, authorisation and object ownership, the
margin rule, filter validation, exports, data integrity, and query-count
regressions. No network access or fixtures required.

---

## Permission model

There are exactly two application roles, and **`role` is authoritative**.

| | Staff | Admin |
|---|---|---|
| Own bookings: view / create / edit / delete | ✅ | ✅ |
| Other users' bookings | ❌ (404) | ✅ |
| Admin dashboard, user & portal management | ❌ (403) | ✅ |
| Excel / PDF export | ❌ (403) | ✅ |
| Django admin site (`/django-admin/`) | ❌ | only if `is_superuser` |

- `is_superuser` is for the Django admin site. It **always implies** panel
  access, so a superuser is never locked out.
- Everything else keys off `role`. One decorator,
  `adminpanel.permissions.panel_admin_required`, enforces it across every admin
  view — there is no second copy of the rule.
- Staff booking access is scoped in the query itself
  (`get_object_or_404(TravelBooking, pk=pk, entered_by=request.user)`), so
  another user's booking returns **404**, not 403.
- An administrator cannot remove their own Admin role or deactivate their own
  account — that is the one change they could not undo from inside the app.

Anonymous users are sent to the login page (with `next` preserved); signed-in
staff hitting an admin URL get a 403 page, because signing in again would not
help.

---

## Export system

Both exports are driven by the **same** `BookingFilterForm` as the list screen,
so an export always covers exactly the rows displayed. The export links carry
the active filters in their query string.

**Excel** (`adminpanel/exports.py :: build_workbook`) — the Viva logo embedded
byte-for-byte, report title, generation timestamp, the active filters, the
booking rows, and a totals row. Money cells carry a `#,##0.00` format and the
header row is frozen and repeated when printing.

**PDF** (`build_pdf`) — landscape A4, built with reportlab's platypus so it
**paginates properly across as many pages as needed**; the table header repeats
on every page and every page is numbered. Negative margins are printed in red.

### Money handling

Every figure is a `Decimal` end to end, and **all three totals come from a
database `SUM`**, never from accumulating rows in Python. That is the rule that
keeps the exported total identical to the on-screen total.

One honest limitation: the `.xlsx` format itself stores numbers as IEEE-754
doubles (ECMA-376), and openpyxl serialises at full double precision — a cell
holding `0.07` is written as `0.07000000000000001`. No library can place a true
decimal in a numeric Excel cell. What is guaranteed is that nothing is
*computed* in float and that every cell is formatted to two decimals. The PDF
has no such constraint; its values are formatted from `Decimal` directly.

### Size limit

An export above `EXPORT_MAX_ROWS` (default 10,000) is refused with a message
asking the user to narrow the range, rather than exhausting a worker.

---

## Sign-in / sign-out notifications

When anyone signs in or out, VivaCalc emails the addresses listed in
`AUTH_NOTIFY_RECIPIENTS` with the username, role, timestamp, IP address and
device.

```ini
# .env
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=sender@yourdomain.com
EMAIL_HOST_PASSWORD=<gmail app password>
DEFAULT_FROM_EMAIL=sender@yourdomain.com

AUTH_NOTIFY_ENABLED=True
AUTH_NOTIFY_RECIPIENTS=ops@yourdomain.com,manager@yourdomain.com
AUTH_NOTIFY_ON_LOGIN=True
AUTH_NOTIFY_ON_LOGOUT=True
AUTH_NOTIFY_USER_TOO=False
```

Verify without logging in and out repeatedly:

```bash
python manage.py test_auth_email
python manage.py test_auth_email --event logout --user admin
```

It prints the effective configuration first, so a blank password or empty
recipient list is obvious before anything is sent.

### Gmail specifics

`EMAIL_HOST_PASSWORD` must be a **Gmail app password**, not the account
password — Google rejects the account password for SMTP. Generate one at
<https://myaccount.google.com/apppasswords> (2-Step Verification must be on).
Google displays it as `abcd efgh ijkl mnop`; the spaces are stripped
automatically, so either form pastes fine.

An app password grants full send **and read** access to that mailbox and
bypasses 2FA. Treat it as a credential: it belongs only in `.env` (gitignored),
never in source, a screenshot, or a chat message. If one is ever exposed,
revoke it on that page and generate a new one.

### Failure behaviour

**Mail never blocks or breaks authentication.** Sending happens on a background
thread and every exception is caught and logged, so if Gmail is unreachable,
the app password has been revoked, or the mailbox is full, people still sign in
and out normally — they simply get no email. The failure is recorded in
`logs/vivacalc.log` with the event and username.

This is covered by tests that simulate a refused connection, an SMTP
authentication rejection and a broken template, asserting the session is still
valid afterwards.

Notifications fire on Django's `user_logged_in` / `user_logged_out` signals, so
they also cover sign-ins through the Django admin site, not just the app's own
login page. A *failed* sign-in sends nothing (those are in the log and are
rate-limited by the throttle).

## Production deployment

```bash
export DJANGO_SETTINGS_MODULE=vivacalc.settings.prod
export DJANGO_SECRET_KEY="…"
export ALLOWED_HOSTS="vivacalc.example.com"
export CSRF_TRUSTED_ORIGINS="https://vivacalc.example.com"
export DATABASE_URL="postgres://…"

python manage.py check --deploy     # must report zero issues
python manage.py migrate --noinput
python manage.py createcachetable   # backs the login throttle
python manage.py collectstatic --noinput

gunicorn vivacalc.wsgi:application --workers 3 --bind 127.0.0.1:8000
```

Put nginx (or any TLS terminator) in front, serving `STATIC_ROOT` at `/static/`
and `MEDIA_ROOT` at `/media/`.

- **Health check:** `GET /healthz/` returns `200 ok` when the database answers,
  `503` otherwise. It is public and exposes nothing.
- **Logs:** line-delimited JSON on stdout. Authentication failures, lockouts,
  exports, user creation/deletion and booking deletion are all logged with the
  acting user's id.
- **Cache:** the login throttle needs a cache shared across worker processes.
  Production uses Django's database cache, hence `createcachetable`. Redis is a
  drop-in replacement if you already run one.

---

## Security

`python manage.py check --deploy` reports **zero issues** under
`vivacalc.settings.prod`.

- Secrets come from the environment; `DJANGO_SECRET_KEY` has no fallback.
- `DEBUG = False` is the default everywhere except `settings.dev`.
- HTTPS enforced: `SECURE_SSL_REDIRECT`, HSTS (1 year, subdomains, preload).
- Cookies: `Secure`, `HttpOnly`, `SameSite=Lax` for both session and CSRF.
- `SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_REFERRER_POLICY=same-origin`,
  `X_FRAME_OPTIONS=DENY`, cross-origin opener policy.
- CSRF protection on every state-changing form; **logout is POST-only**.
- Login throttling by username *and* client IP, with a cool-off.
- Passwords use Django's PBKDF2 with a 10-character minimum.
- Request-body size limits to blunt trivial denial of service.

> **If you are upgrading an existing deployment:** the previous `SECRET_KEY` was
> committed in source and must be treated as public. Generate a new one. Doing
> so invalidates all existing sessions, which is the desired outcome.

---

## Project structure

```
vivacalc/
├── vivacalc/                  project package
│   ├── settings/
│   │   ├── base.py            shared, secure-by-default
│   │   ├── dev.py             local development
│   │   ├── prod.py            production
│   │   └── env.py             dependency-free env reader
│   ├── urls.py                root routes + error handlers
│   ├── errors.py              branded 403 / 404 / 500 views
│   ├── context_processors.py  brand constants for templates
│   └── logging_utils.py       JSON log formatter
├── adminpanel/                models + admin panel
│   ├── models.py              CustomUser, Portal, TravelBooking
│   ├── filters.py             the shared BookingFilterForm
│   ├── permissions.py         panel_admin_required
│   ├── exports.py             Excel + PDF builders
│   ├── forms.py  views.py  urls.py  admin.py
│   └── migrations/
├── vivapanel/                 staff workspace + authentication
│   ├── views.py               login, dashboard, own-booking CRUD, healthz
│   ├── throttle.py            login brute-force protection
│   └── urls.py
├── templates/
│   ├── base.html              the one app shell, both roles
│   ├── components/            sidebar, field, messages, pagination, empty state
│   ├── auth/  panel/  staff/  errors/
├── static/
│   ├── css/style.css          design system
│   ├── css/dashboard.css      dashboard layout
│   ├── css/responsive.css     breakpoints + mobile table restacking
│   ├── js/app.js              progressive enhancement only
│   └── logo.png               the Viva logo — do not modify
└── tests/                     99 tests
```

### Branding

`static/logo.png` is the Viva Holidays logo and must not be edited, recoloured,
cropped or regenerated. The UI palette is derived *from* it: `#EC1C24` (Viva
red) and `#A6A8AB` (Viva grey), both sampled from the artwork.

The file has **no alpha channel** — its white background is part of the image —
so every surface it sits on is deliberately white. Do not place it on a tint.

---

## Known limitations

- **Excel decimal storage** — see *Money handling* above. A format constraint,
  not an arithmetic one.
- **No `margin == sell - buy` database constraint.** It was implemented, then
  removed in `0006`: SQLite has no decimal type, so the check rejected
  legitimate rows (`0.30 - 0.10` evaluates to `0.19999999999999998` there). The
  rule is enforced in `TravelBooking.save()` and covered by tests. On
  PostgreSQL, whose `NUMERIC` arithmetic is exact, it can be reinstated.
- **Login throttle correctness depends on a shared cache.** With
  `LocMemCache` and *n* worker processes the effective limit is *n* × the
  configured value. `settings.prod` uses the database cache for this reason.
- **No audit history on bookings.** Price edits and deletions are logged but
  not versioned. If "who changed this number, and when" becomes a requirement,
  `django-simple-history` on `TravelBooking` is the small answer.
- **Exports are synchronous.** Fine at the configured 10,000-row ceiling; a
  larger ledger would want a background job.
