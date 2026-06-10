from __future__ import annotations

import importlib
import logging
import pkgutil
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)
CollectorFunc = Callable[..., Coroutine[Any, Any, list[dict[str, Any]]]]
_R: dict[str, "CollectorMeta"] = {}


@dataclass
class CollectorMeta:
    name: str
    description: str
    enabled: bool = True
    rate_limit_rps: float = 1.0
    timeout: float = 30.0
    func: CollectorFunc | None = None
    tags: list[str] = field(default_factory=list)
    module: str = ""


def collector(
    name: str,
    *,
    description: str = "",
    enabled: bool = True,
    rate_limit_rps: float = 1.0,
    timeout: float = 30.0,
    tags: list[str] | None = None,
) -> Callable[[CollectorFunc], CollectorFunc]:
    def dec(func: CollectorFunc) -> CollectorFunc:
        _R[name] = CollectorMeta(
            name=name,
            description=description or (func.__doc__ or "")[:120],
            enabled=enabled,
            rate_limit_rps=rate_limit_rps,
            timeout=timeout,
            func=func,
            tags=list(tags or []),
            module=getattr(func, "__module__", ""),
        )
        return func

    return dec


class PluginRegistry:
    def __init__(self, package: str = "ai_finder.collectors") -> None:
        self._pkg = package
        self._done = False

    def discover(self) -> "PluginRegistry":
        if self._done:
            return self
        self._done = True
        try:
            pkg = importlib.import_module(self._pkg)
            for _, mn, _ in pkgutil.iter_modules(getattr(pkg, "__path__", [])):
                try:
                    importlib.import_module(f"{self._pkg}.{mn}")
                except Exception as e:
                    log.warning("Registry: failed %s: %s", mn, e)
        except ImportError as e:
            log.error("Registry: %s", e)
        return self

    def get_enabled(self) -> list[CollectorMeta]:
        return [m for m in _R.values() if m.enabled]

    def get(self, n: str) -> CollectorMeta | None:
        return _R.get(n)

    def all(self) -> dict:
        return dict(_R)

    def names(self) -> list[str]:
        return list(_R)

    def enable(self, n: str) -> None:
        if n in _R:
            _R[n].enabled = True

    def disable(self, n: str) -> None:
        if n in _R:
            _R[n].enabled = False

    def clear(self) -> None:
        _R.clear()
        self._done = False

    def configure_from_meta(self, limiter: Any) -> None:
        for m in self.get_enabled():
            if hasattr(limiter, "configure"):
                limiter.configure(m.name, m.rate_limit_rps)

    def stats(self) -> dict:
        return {"total": len(_R), "enabled": sum(1 for m in _R.values() if m.enabled)}


_dr: PluginRegistry | None = None


def get_registry() -> PluginRegistry:
    global _dr
    if _dr is None:
        _dr = PluginRegistry()
    return _dr
