from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_finder.commands import CommandBus
    from ai_finder.container import Container
    from ai_finder.queries import QueryBus

log = logging.getLogger(__name__)


async def build_container() -> "Container":
    from ai_finder.container import Container
    from ai_finder.fast_io import install_uvloop

    install_uvloop()
    c = Container()
    try:
        from ai_finder.db import DB  # type: ignore

        c.singleton(DB, lambda: DB(os.getenv("DB_PATH", "ai_finder.db")))
    except ImportError:
        pass
    try:
        from ai_finder.events import EventBus  # type: ignore

        c.singleton(EventBus, lambda: EventBus())
    except ImportError:
        pass
    from ai_finder.memory_cache import MemoryCache
    from ai_finder.ml_scorer import MLScorer
    from ai_finder.rate_limiter import RateLimiter

    c.singleton(RateLimiter, lambda: RateLimiter(default_rate=1.0))
    c.singleton(MemoryCache, lambda: MemoryCache(max_size=2048, default_ttl=300.0))
    c.singleton(MLScorer, lambda: MLScorer().fit())
    from ai_finder.registry import PluginRegistry

    async def _reg() -> PluginRegistry:
        lim = await c.resolve(RateLimiter)
        r = PluginRegistry()
        r.discover()
        r.configure_from_meta(lim)
        return r

    c.singleton(PluginRegistry, _reg)
    return c


def build_command_bus() -> "CommandBus":
    from ai_finder.commands import create_default_command_bus

    return create_default_command_bus()


def build_query_bus() -> "QueryBus":
    from ai_finder.queries import QueryBus

    return QueryBus()
