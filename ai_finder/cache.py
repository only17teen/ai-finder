from __future__ import annotations
from ai_finder.cache_base import Cache
from ai_finder.memory_cache import MemoryCache
from ai_finder.cache_warming import get_or_load,background_warm
AsyncTTLCache=MemoryCache
