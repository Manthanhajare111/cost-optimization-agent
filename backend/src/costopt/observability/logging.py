"""Structured standard-library logging for local and hosted CostOpt runtimes."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from costopt.config import settings


_STANDARD_LOG_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__)
_HANDLER_MARKER = "_costopt_structured_handler"


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_FIELDS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging() -> None:
    """Configure CostOpt logging once without replacing host-owned handlers."""
    root_logger = logging.getLogger()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root_logger.setLevel(level)
    if any(getattr(handler, _HANDLER_MARKER, False) for handler in root_logger.handlers):
        return

    handler = logging.StreamHandler()
    setattr(handler, _HANDLER_MARKER, True)
    if settings.log_format.lower() == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
