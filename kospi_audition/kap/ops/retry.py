"""Lightweight retry decorator with exponential back-off.

The data collection and notification calls hit external services
(pykrx, DART, Slack, SMTP) that fail transiently. Wrapping them with
``@retry`` lets the daily scheduler tolerate flaky networks without
losing the run.
"""

from __future__ import annotations

import functools
import time
from typing import Callable, TypeVar

from loguru import logger

T = TypeVar("T")


def retry(
    attempts: int = 3,
    initial_delay: float = 2.0,
    backoff: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Retry the wrapped function up to ``attempts`` times with exp back-off."""

    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapped(*args: object, **kwargs: object) -> T:
            delay = initial_delay
            last_exc: BaseException | None = None
            for i in range(1, attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if i == attempts:
                        logger.error("{} failed after {} attempts: {}", fn.__name__, attempts, exc)
                        raise
                    logger.warning(
                        "{} attempt {}/{} failed ({}); retrying in {:.1f}s",
                        fn.__name__, i, attempts, exc, delay,
                    )
                    time.sleep(delay)
                    delay *= backoff
            # Unreachable; raise to satisfy type checker.
            if last_exc:
                raise last_exc
            raise RuntimeError("retry: unreachable")

        return wrapped

    return deco
