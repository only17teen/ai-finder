from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Query:
    query_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(frozen=True, slots=True)
class GetSiteQuery(Query):
    domain: str = ""


@dataclass(frozen=True, slots=True)
class GetTopSitesQuery(Query):
    limit: int = 20
    min_score: int = 50


@dataclass(frozen=True, slots=True)
class GetStatsQuery(Query):
    pass


class QueryBus:
    def __init__(self) -> None:
        self._h: dict[type, Any] = {}
        self._c: dict[str, Any] = {}
        self._lock: asyncio.Lock | None = None

    def _lk(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def register(self, t: type, h: Any) -> "QueryBus":
        self._h[t] = h
        return self

    async def ask(self, q: Any) -> Any:
        h = self._h.get(type(q))
        if h is None:
            raise KeyError(f"No handler for {type(q).__name__!r}")
        return await h.handle(q)

    async def ask_cached(self, q: Any, key: str) -> Any:
        if key in self._c:
            return self._c[key]
        async with self._lk():
            if key in self._c:
                return self._c[key]
            r = await self.ask(q)
            self._c[key] = r
            return r

    def invalidate(self, key: str) -> None:
        self._c.pop(key, None)

    def clear_cache(self) -> None:
        self._c.clear()
