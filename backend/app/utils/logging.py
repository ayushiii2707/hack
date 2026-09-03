"""Application logging.

Developer-facing only. Business events go through the audit service.
Each line carries the ISO timestamp and the current request id (when set) so
logs and audit rows can be correlated during an incident.
"""
from __future__ import annotations

import json
import logging
import os
import sys

from app.core.context import get_request_id

_CONFIGURED = False


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = level if level is not None else getattr(
        logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    if os.environ.get("LOG_JSON", "").lower() in ("1", "true", "yes"):
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s :: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
