"""A tiny in-process stand-in for the handful of Redis commands the store uses.

Keeps the shared-store tests honest without a server or an extra dependency:
two backends pointed at one FakeRedis behave exactly like two app instances
pointed at one Redis.
"""

from __future__ import annotations

import fnmatch


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.hashes: dict[str, dict[str, bytes]] = {}
        self.expiries: dict[str, int] = {}

    def ping(self) -> bool:
        return True

    def setex(self, key: str, seconds: int, value: bytes) -> None:
        self.values[key] = value
        self.expiries[key] = seconds

    def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            removed += int(self.values.pop(key, None) is not None)
            removed += int(self.hashes.pop(key, None) is not None)
            self.expiries.pop(key, None)
        return removed

    def scan_iter(self, match: str = "*", count: int = 100):
        for key in list(self.values) + list(self.hashes):
            if fnmatch.fnmatch(key, match):
                yield key

    def hget(self, name: str, key: str) -> bytes | None:
        return self.hashes.get(name, {}).get(key)

    def hset(self, name: str, key: str, value: bytes) -> int:
        self.hashes.setdefault(name, {})[key] = value
        return 1

    def hlen(self, name: str) -> int:
        return len(self.hashes.get(name, {}))

    def expire(self, key: str, seconds: int) -> bool:
        self.expiries[key] = seconds
        return True

    def incr(self, key: str) -> int:
        value = int(self.values.get(key, b"0")) + 1
        self.values[key] = str(value).encode()
        return value
