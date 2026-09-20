"""Per-IP request throttling, so one client cannot drain the LLM budget.

ponytail: in-memory and per-process - fine for a single instance. Behind more
than one worker, move the counters to Redis.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from backend import config

_WINDOW_SECONDS = 60
_MAX_TRACKED_CLIENTS = 5000

_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def check(request: Request) -> None:
    """Raise HTTP 429 if this client is over the limit for the last minute."""
    # X-Forwarded-For is spoofable, so we throttle on the real socket address.
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()

    with _lock:
        if len(_hits) > _MAX_TRACKED_CLIENTS:
            _hits.clear()
        recent = _hits[client]
        while recent and now - recent[0] > _WINDOW_SECONDS:
            recent.popleft()
        if len(recent) >= config.RATE_LIMIT_PER_MINUTE:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please wait a minute and try again.",
                headers={"Retry-After": str(_WINDOW_SECONDS)},
            )
        recent.append(now)


def reset() -> None:
    with _lock:
        _hits.clear()
