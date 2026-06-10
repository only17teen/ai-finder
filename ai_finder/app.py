from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class Application:
    def __init__(self, name: str = "ai-finder") -> None:
        self.name = name
        self._c = self._cb = self._qb = self._tm = None

    async def __aenter__(self) -> "Application":
        await self._startup()
        return self

    async def __aexit__(self, *_: Any) -> None:
        log.info("%s stopped", self.name)

    async def _startup(self) -> None:
        import logging as _l

        from ai_finder.composition import build_command_bus, build_container, build_query_bus
        from ai_finder.secrets import SecretMaskingFilter
        from ai_finder.supervisor import TaskManager

        _l.getLogger().addFilter(SecretMaskingFilter())
        self._c = await build_container()
        self._cb = build_command_bus()
        self._qb = build_query_bus()
        self._tm = TaskManager(self.name)

    async def run(self) -> None:
        from ai_finder.loop_monitor import monitor_event_loop
        from ai_finder.supervisor import install_signal_handlers

        await self._startup()
        async with self._tm:
            install_signal_handlers(self._tm)
            self._tm.spawn(monitor_event_loop(), name="loop-monitor")
            self._tm.spawn(self._tm.wait_for_shutdown(), name="sentinel")
            log.info("%s running", self.name)

    @property
    def container(self) -> Any:
        if not self._c:
            raise RuntimeError("Not started")
            return self._c

    @property
    def command_bus(self) -> Any:
        if not self._cb:
            raise RuntimeError("Not started")
            return self._cb

    @property
    def task_manager(self) -> Any:
        if not self._tm:
            raise RuntimeError("Not started")
            return self._tm
