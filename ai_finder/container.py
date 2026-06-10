from __future__ import annotations
import asyncio, inspect
from collections.abc import Callable
from typing import Any, Generic, TypeVar
T = TypeVar("T")
class Provider(Generic[T]):
    async def get(self) -> T: raise NotImplementedError
class SingletonProvider(Provider[T]):
    def __init__(self, f: Callable[[], Any]) -> None:
        self._f=f; self._i: T|None=None; self._lock: asyncio.Lock|None=None
    def _lk(self) -> asyncio.Lock:
        if self._lock is None: self._lock=asyncio.Lock()
        return self._lock
    async def get(self) -> T:
        if self._i is None:
            async with self._lk():
                if self._i is None:
                    r=self._f(); self._i=await r if inspect.isawaitable(r) else r
        return self._i  # type: ignore[return-value]
    def override(self,v:T)->None: self._i=v
class TransientProvider(Provider[T]):
    def __init__(self,f:Callable[[],Any])->None: self._f=f
    async def get(self)->T:
        r=self._f(); return await r if inspect.isawaitable(r) else r
class Container:
    def __init__(self)->None: self._p:dict[type,Provider[Any]]={}
    def singleton(self,t:type[T],f:Callable[[],Any])->"Container":
        self._p[t]=SingletonProvider(f); return self
    def transient(self,t:type[T],f:Callable[[],Any])->"Container":
        self._p[t]=TransientProvider(f); return self
    def instance(self,t:type[T],v:T)->"Container":
        p:SingletonProvider[T]=SingletonProvider(lambda:v); p.override(v); self._p[t]=p; return self
    def override(self,t:type[T],f:Callable[[],Any])->"Container":
        self._p[t]=SingletonProvider(f); return self
    async def resolve(self,t:type[T])->T:
        if t not in self._p: raise KeyError(f"No provider for {t!r}")
        return await self._p[t].get()
    def is_registered(self,t:type)->bool: return t in self._p
    def registered_types(self)->list[type]: return list(self._p.keys())
