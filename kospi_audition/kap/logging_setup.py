"""Loguru-based logging setup."""

from __future__ import annotations

import sys

from loguru import logger

from kap import config


def configure_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(sys.stderr, format=config.LOG_FORMAT, level=level, enqueue=False)
