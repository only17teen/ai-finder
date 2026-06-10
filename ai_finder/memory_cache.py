from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class _E(Generic[V]):
    __slots__ = ("value", "expires_at")

    def __init__(self, v: V, ttl: float | None) -> None:
        self.value = v
        self.expires_at = time.monotonic() + ttl if ttl is not None else None


class MemoryCache(Generic[K, V]):
    def __init__(self, max_size: int = 1024, default_ttl: float | None = 300.0) -> None:
        self._s: OrderedDict[K, _E[V]] = OrderedDict()
        self._mx = max_size
        self._ttl = default_ttl
        self._lock: asyncio.Lock | None = None
        self._hits = self._misses = self._evictions = 0

    def _lk(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def get(self, key: K) -> V | None:
        async with self._lk():
            e = self._s.get(key)
            if e is None:
                self._misses += 1
                return None
            if e.expires_at is not None and time.monotonic() > e.expires_at:
                del self._s[key]
                self._misses += 1
                self._evictions += 1
                return None
            self._s.move_to_end(key)
            self._hits += 1
            return e.value

    async def set(self, key: K, value: V, ttl: float | None = None) -> None:
        async with self._lk():
            self._s[key] = _E(value, ttl if ttl is not None else self._ttl)
            self._s.move_to_end(key)
            while len(self._s) > self._mx:
                self._s.popitem(last=False)
                self._evictions += 1

    async def delete(self, key: K) -> None:
        async with self._lk():
            self._s.pop(key, None)

    async def exists(self, key: K) -> bool:
        return await self.get(key) is not None

    async def clear(self) -> None:
        async with self._lk():
            self._s.clear()
            self._hits = self._misses = self._evictions = 0

    @property
    def hit_rate(self) -> float:
        t = self._hits + self._misses
        return self._hits / t if t else 0.0

    @property
    def size(self) -> int:
        return len(self._s)

    @property
    def evictions(self) -> int:
        return self._evictions

    def stats(self) -> dict:
        return {
            "size": self.size,
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "hit_rate": round(self.hit_rate, 4),
        }
