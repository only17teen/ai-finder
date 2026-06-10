from __future__ import annotations

import inspect
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)
Dispatch = Callable[[Any], Coroutine[Any, Any, Any]]
Middleware = Callable[[Any, Dispatch], Coroutine[Any, Any, Any]]


@dataclass(frozen=True, slots=True)
class Command:
    command_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(frozen=True, slots=True)
class RunCollectorCommand(Command):
    collector_name: str = ""
    limit: int = 50


@dataclass(frozen=True, slots=True)
class VerifySiteCommand(Command):
    domain: str = ""
    url: str = ""
    force: bool = False


@dataclass(frozen=True, slots=True)
class SendNotificationCommand(Command):
    channel: str = "telegram"
    site_id: int = 0
    message: str = ""


async def logging_middleware(cmd: Any, nxt: Dispatch) -> Any:
    log.debug("CMD %s", type(cmd).__name__)
    try:
        return await nxt(cmd)
    except Exception as e:
        log.error("CMD %s failed: %s", type(cmd).__name__, e)
        raise


async def timing_middleware(cmd: Any, nxt: Dispatch) -> Any:
    t0 = time.perf_counter()
    try:
        return await nxt(cmd)
    finally:
        log.debug("CMD %s %.2fms", type(cmd).__name__, (time.perf_counter() - t0) * 1000)


async def validation_middleware(cmd: Any, nxt: Dispatch) -> Any:
    if hasattr(cmd, "validate"):
        r = cmd.validate()
        if inspect.isawaitable(r):
            await r
    return await nxt(cmd)


class CommandBus:
    def __init__(self) -> None:
        self._h: dict[type, Any] = {}
        self._mw: list[Middleware] = []

    def register(self, t: type, h: Any) -> "CommandBus":
        self._h[t] = h
        return self

    def use(self, mw: Middleware) -> "CommandBus":
        self._mw.append(mw)
        return self

    async def dispatch(self, cmd: Any) -> Any:
        h = self._h.get(type(cmd))
        if h is None:
            raise KeyError(f"No handler for {type(cmd).__name__!r}")

        async def base(c: Any) -> Any:
            return await h.handle(c)

        pipeline: Dispatch = base
        for mw in reversed(self._mw):
            _p: Dispatch = pipeline
            _m: Middleware = mw

            async def step(c: Any, *, _pp: Dispatch = _p, _mm: Middleware = _m) -> Any:
                return await _mm(c, _pp)

            pipeline = step
        return await pipeline(cmd)

    def is_registered(self, t: type) -> bool:
        return t in self._h


def create_default_command_bus() -> CommandBus:
    return CommandBus().use(logging_middleware).use(validation_middleware).use(timing_middleware)
