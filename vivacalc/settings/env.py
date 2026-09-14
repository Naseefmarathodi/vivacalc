"""Minimal environment-variable reader.

Deliberately dependency-free: the project only needs a handful of typed
lookups, so a third-party settings library is not justified here.

Values come from the process environment. ``read_dotenv()`` additionally loads
``BASE_DIR/.env`` for local development; real deployments should set the
variables in the process environment instead of shipping a file.
"""

from __future__ import annotations

import os
from pathlib import Path


class ImproperlyConfigured(Exception):
    """Raised when a required setting is missing, so startup fails loudly."""


_MISSING = object()


def read_dotenv(path: Path) -> None:
    """Load ``KEY=value`` lines from *path*. Existing env vars always win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env(name: str, default=_MISSING) -> str:
    """Return a required string setting, or *default* if one was supplied."""
    value = os.environ.get(name)
    if value is None or value == "":
        if default is _MISSING:
            raise ImproperlyConfigured(
                f"Required environment variable {name!r} is not set. "
                f"See .env.example for the full list."
            )
        return default
    return value


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer, got {raw!r}") from exc


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]
