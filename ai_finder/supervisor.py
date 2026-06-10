from __future__ import annotations

import asyncio
import logging
import signal
import sys
from collections.abc import Callable, Coroutine
from typing import Any

log = logging.getLogger(__name__)
if sys.version_info >= (3, 11):
    from asyncio import TaskGroup as _TG
else:

    class _TG:  # type: ignore
        def __init__(self) -> None:
            self._t: list[asyncio.Task] = []

        async def __aenter__(self) -> "_TG":
            return self

        def create_task(self, c: Any, *, name: str | None = None) -> asyncio.Task:
            t = asyncio.create_task(c, name=name)
            self._t.append(t)
            return t

        async def __aexit__(self, *_: Any) -> None:
            if not self._t:
                return
            rs = await asyncio.gather(*self._t, return_exceptions=True)
            errs = [
                r
                for r in rs
                if isinstance(r, BaseException) and not isinstance(r, asyncio.CancelledError)
            ]
            if errs:
                raise errs[0] from None


async def supervised(
    factory: Callable[[], Coroutine[Any, Any, Any]],
    name: str,
    *,
    max_restarts: int = 5,
    backoff: float = 1.0,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    for i in range(max_restarts):
        if shutdown_event and shutdown_event.is_set():
            return
        try:
            log.info("supervised %s attempt %d", name, i + 1)
            await factory()
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if i >= max_restarts - 1:
                raise
            wait = min(backoff * (2**i), 60.0)
            log.warning("supervised %s retry in %.1fs: %s", name, wait, e)
            await asyncio.sleep(wait)


class TaskManager:
    def __init__(self, name: str = "TaskManager") -> None:
        self.name = name
        self._g: _TG | None = None
        self._cm: _TG | None = None
        self._sd: asyncio.Event | None = None

    def _ev(self) -> asyncio.Event:
        if self._sd is None:
            self._sd = asyncio.Event()
        return self._sd

    async def __aenter__(self) -> "TaskManager":
        self._cm = _TG()
        self._g = await self._cm.__aenter__()
        return self

    async def __aexit__(self, *e: Any) -> Any:
        return await self._cm.__aexit__(*e) if self._cm else None

    def spawn(self, coro: Coroutine[Any, Any, Any], *, name: str | None = None) -> asyncio.Task:
        if self._g is None:
            raise RuntimeError("Use as async context manager")
        return self._g.create_task(coro, name=name)

    def spawn_supervised(
        self,
        factory: Callable[[], Coroutine[Any, Any, Any]],
        *,
        name: str,
        max_restarts: int = 5,
        backoff: float = 1.0,
    ) -> asyncio.Task:
        return self.spawn(
            supervised(
                factory, name, max_restarts=max_restarts, backoff=backoff, shutdown_event=self._ev()
            ),
            name=f"sup:{name}",
        )

    def signal_shutdown(self) -> None:
        self._ev().set()

    async def wait_for_shutdown(self) -> None:
        await self._ev().wait()


def install_signal_handlers(tm: TaskManager) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    def _s() -> None:
        tm.signal_shutdown()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _s)
        except (NotImplementedError, ValueError):
            signal.signal(sig, lambda s, f: _s())
