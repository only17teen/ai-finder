from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from ai_finder.cache_base import Cache

V = TypeVar("V")
log = logging.getLogger(__name__)
_if: dict[Any, asyncio.Future[Any]] = {}
_bg: set[asyncio.Task[Any]] = set()


async def get_or_load(
    cache: Cache[Any, V], key: Any, loader: Callable[[Any], Awaitable[V]], ttl: float = 300.0
) -> V:
    v = await cache.get(key)
    if v is not None:
        return v
    if key in _if:
        return await asyncio.shield(_if[key])
    fut: asyncio.Future[V] = asyncio.get_running_loop().create_future()
    _if[key] = fut
    try:
        loaded = await loader(key)
        await cache.set(key, loaded, ttl)
        fut.set_result(loaded)
        return loaded
    except Exception as e:
        fut.set_exception(e)
        raise
    finally:
        _if.pop(key, None)


def background_warm(
    cache: Cache[Any, Any],
    loader: Callable[[Any], Awaitable[Any]],
    keys: list[Any],
    ttl: float = 300.0,
) -> None:
    async def _w() -> None:
        rs = await asyncio.gather(*[loader(k) for k in keys], return_exceptions=True)
        for k, v in zip(keys, rs):
            if not isinstance(v, Exception):
                await cache.set(k, v, ttl)

    t = asyncio.create_task(_w())
    _bg.add(t)
    t.add_done_callback(_bg.discard)
