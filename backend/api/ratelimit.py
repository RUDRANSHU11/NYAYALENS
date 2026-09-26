"""Per-IP request throttling, so one client cannot drain the LLM budget.

With ``REDIS_URL`` set the counters live in Redis, so the limit is enforced
across every instance. Without it they are per-process, which is correct for a
single instance and degrades to "per instance" rather than failing.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from backend import config
from backend.rag import store

_WINDOW_SECONDS = 60
_MAX_TRACKED_CLIENTS = 5000

_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def check(request: Request) -> None:
    """Raise HTTP 429 if this client is over the limit for the last minute."""
    # X-Forwarded-For is spoofable, so we throttle on the real socket address.
    client = request.client.host if request.client else "unknown"

    shared = getattr(store.backend(), "hit_counter", None)
    over_limit = (
        shared(f"{client}:{int(time.time()) // _WINDOW_SECONDS}", _WINDOW_SECONDS)
        > config.RATE_LIMIT_PER_MINUTE
        if shared is not None
        else _local_over_limit(client)
    )
    if over_limit:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a minute and try again.",
            headers={"Retry-After": str(_WINDOW_SECONDS)},
        )


def reset() -> None:
    with _lock:
        _hits.clear()


def _local_over_limit(client: str) -> bool:
    now = time.monotonic()
    with _lock:
        if len(_hits) > _MAX_TRACKED_CLIENTS:
            _hits.clear()
        recent = _hits[client]
        while recent and now - recent[0] > _WINDOW_SECONDS:
            recent.popleft()
        if len(recent) >= config.RATE_LIMIT_PER_MINUTE:
            return True
        recent.append(now)
        return False
