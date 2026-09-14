"""Session lifetime rules.

Two independent limits, both enforced on the server:

* **Absolute cap** — a session dies exactly ``SESSION_MAX_AGE`` after sign-in,
  no matter what the user does. Refreshing, clicking and keeping the browser
  open do not extend it.
* **Idle timeout** — a session also dies after ``SESSION_IDLE_TIMEOUT`` with no
  requests. This can only ever shorten a session, never push it past the
  absolute cap.

How the absolute cap resists being reset
----------------------------------------
Django's default is a *sliding* expiry: ``SESSION_SAVE_EVERY_REQUEST = True``
rewrites the cookie on every request, so an open tab that polls stays alive
forever. Two things prevent that here:

1. ``SESSION_SAVE_EVERY_REQUEST`` is off.
2. At login the expiry is pinned with ``set_expiry(<datetime>)``. Passing a
   *datetime* (not an integer) makes Django store an absolute instant, so
   later saves — which do still happen, because the idle timestamp is written
   into the session — recompute the same deadline instead of moving it.

The deadline is therefore fixed at login and survives every subsequent write.
"""

from __future__ import annotations

import datetime as _dt

from django.conf import settings
from django.utils import timezone

# Session keys. Leading underscore keeps them out of template context by
# convention and signals that they are framework-level, not app data.
STARTED_AT = "_viva_started_at"
LAST_SEEN_AT = "_viva_last_seen_at"
LOGOUT_REASON = "_viva_logout_reason"

# Why a session ended, used for the log line and to avoid double-reporting.
REASON_MANUAL = "manual"
REASON_EXPIRED = "session_expired"
REASON_IDLE = "inactive"


def max_age() -> _dt.timedelta:
    return _dt.timedelta(seconds=getattr(settings, "SESSION_MAX_AGE", 3600))


def idle_timeout() -> _dt.timedelta:
    return _dt.timedelta(
        seconds=getattr(settings, "SESSION_IDLE_TIMEOUT", 900)
    )


def _parse(value) -> _dt.datetime | None:
    if not value:
        return None
    try:
        parsed = _dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, _dt.timezone.utc)
    return parsed


def begin(session, now: _dt.datetime | None = None) -> _dt.datetime:
    """Stamp a freshly authenticated session and pin its absolute deadline."""
    now = now or timezone.now()
    deadline = now + max_age()
    session[STARTED_AT] = now.isoformat()
    session[LAST_SEEN_AT] = now.isoformat()
    session.pop(LOGOUT_REASON, None)
    # A datetime pins the deadline; an int would restart it on every save.
    session.set_expiry(deadline)
    return deadline


def started_at(session) -> _dt.datetime | None:
    return _parse(session.get(STARTED_AT))


def last_seen_at(session) -> _dt.datetime | None:
    return _parse(session.get(LAST_SEEN_AT))


def deadline(session) -> _dt.datetime | None:
    start = started_at(session)
    return start + max_age() if start else None


def expiry_reason(session, now: _dt.datetime | None = None) -> str | None:
    """Return why this session should end now, or None if it may continue."""
    now = now or timezone.now()

    start = started_at(session)
    if start is not None and now - start >= max_age():
        return REASON_EXPIRED

    seen = last_seen_at(session)
    if seen is not None and now - seen >= idle_timeout():
        return REASON_IDLE

    return None


def touch(session, now: _dt.datetime | None = None) -> None:
    """Record activity for the idle check.

    Only ever moves the *idle* clock. The absolute deadline is untouched,
    which is what stops activity extending a session past the cap.
    """
    session[LAST_SEEN_AT] = (now or timezone.now()).isoformat()


def seconds_remaining(session, now: _dt.datetime | None = None) -> int:
    """Whole seconds until the absolute cap; 0 once reached."""
    end = deadline(session)
    if end is None:
        return int(max_age().total_seconds())
    return max(int((end - (now or timezone.now())).total_seconds()), 0)
