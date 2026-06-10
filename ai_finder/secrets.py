from __future__ import annotations

import logging
import os
import re
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class SecretBackend(ABC):
    @abstractmethod
    async def get(self, key: str) -> str | None: ...


class EnvBackend(SecretBackend):
    async def get(self, key: str) -> str | None:
        return os.environ.get(key)


class DotenvBackend(SecretBackend):
    def __init__(self, env_file: str = ".env") -> None:
        self._f = env_file
        self._c: dict[str, str] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        try:
            from dotenv import dotenv_values  # type: ignore

            self._c = dict(dotenv_values(self._f))
        except Exception:
            pass
        self._loaded = True

    async def get(self, key: str) -> str | None:
        self._load()
        return self._c.get(key)


class SecretProvider:
    def __init__(self, backends: list[SecretBackend]) -> None:
        self._b = backends

    async def get(self, key: str, required: bool = True) -> str | None:
        for b in self._b:
            v = await b.get(key)
            if v is not None:
                return v
        if required:
            raise RuntimeError(f"Secret {key!r} not found")
        return None

    def invalidate(self) -> None:
        for b in self._b:
            if hasattr(b, "_c"):
                b._c.clear()
            if hasattr(b, "_loaded"):
                b._loaded = False


class SecretMaskingFilter(logging.Filter):
    _P = [
        re.compile(r"(sk[-_][a-zA-Z0-9]{20,})", re.I),
        re.compile(r"(ghp_[a-zA-Z0-9]{36,})", re.I),
        re.compile(r"(?i)(password\s*[=:]\s*)\S+"),
        re.compile(r"(?i)(token\s*[=:]\s*)\S+"),
        re.compile(r"(?i)(secret\s*[=:]\s*)\S+"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for p in self._P:
            msg = p.sub(lambda m: (m.group(1) + "[REDACTED]") if m.lastindex else "[REDACTED]", msg)
        record.msg = msg
        record.args = ()
        return True


def build_secret_provider() -> "SecretProvider":
    return SecretProvider([EnvBackend(), DotenvBackend()])
