"""Login brute-force protection.

Deliberately built on Django's cache framework rather than a third-party
package: the whole rule is ~60 lines, adds no models, no migrations and no
authentication backend, and is covered by the test suite.

Counters are keyed by username *and* client IP, so one attacker cannot lock
out a legitimate user by guessing at their account from elsewhere, and a single
host cannot spray many accounts.

Production note: this is only as correct as the cache is shared. ``prod.py``
uses the database cache backend for exactly this reason — a per-process cache
(LocMemCache) would multiply the effective limit by the worker count.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("vivacalc.auth")

_PREFIX = "login-throttle"


def client_ip(request) -> str:
    """Best-effort client address.

    X-Forwarded-For is only trusted when the deployment says it sits behind a
    proxy, since the header is otherwise attacker-controlled.
    """
    if getattr(settings, "SECURE_PROXY_SSL_HEADER", None):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def _keys(username: str, ip: str) -> list[str]:
    return [
        f"{_PREFIX}:user:{(username or '').strip().lower()[:150]}",
        f"{_PREFIX}:ip:{ip}",
    ]


def _limit() -> int:
    return getattr(settings, "LOGIN_ATTEMPT_LIMIT", 5)


def _cooloff_seconds() -> int:
    return getattr(settings, "LOGIN_ATTEMPT_COOLOFF_MINUTES", 15) * 60


def is_locked_out(username: str, ip: str) -> bool:
    limit = _limit()
    return any(cache.get(key, 0) >= limit for key in _keys(username, ip))


def record_failure(username: str, ip: str) -> int:
    """Count one failed attempt. Returns the highest counter now standing."""
    highest = 0
    timeout = _cooloff_seconds()
    for key in _keys(username, ip):
        # add() only succeeds when the key is absent, which starts the window;
        # incr() then advances it without extending the expiry.
        if cache.add(key, 1, timeout):
            count = 1
        else:
            try:
                count = cache.incr(key)
            except ValueError:  # expired between the add() and the incr()
                cache.set(key, 1, timeout)
                count = 1
        highest = max(highest, count)
    logger.warning(
        "login failed",
        extra={"username": username, "client_ip": ip, "attempts": highest},
    )
    return highest


def reset(username: str, ip: str) -> None:
    """Clear the counters after a successful sign-in."""
    cache.delete_many(_keys(username, ip))


def attempts_remaining(username: str, ip: str) -> int:
    used = max((cache.get(key, 0) for key in _keys(username, ip)), default=0)
    return max(_limit() - used, 0)
