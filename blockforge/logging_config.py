"""Logging setup. Never log private keys, passwords or API keys."""
from __future__ import annotations

import json
import logging
import sys
import time


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, separators=(",", ":"))


def setup_logging(level: str = "INFO", json_format: bool = False) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        _JsonFormatter() if json_format
        else logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())