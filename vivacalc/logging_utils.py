"""Structured logging helpers."""

from __future__ import annotations

import datetime as _dt
import json
import logging

_RESERVED = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)))


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for log aggregators.

    Extra keyword arguments passed as ``logger.info(msg, extra={...})`` are
    merged into the object, which is how the app attaches user ids and request
    paths to auth and export events.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": _dt.datetime.fromtimestamp(
                record.created, tz=_dt.timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                try:
                    json.dumps(value)
                except (TypeError, ValueError):
                    value = repr(value)
                payload[key] = value
        return json.dumps(payload, default=str)
