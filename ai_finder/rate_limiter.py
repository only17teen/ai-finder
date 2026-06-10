from __future__ import annotations
import asyncio,logging,time
log=logging.getLogger(__name__)
class TokenBucket:
    def __init__(self,rate:float,capacity:float)->None:
        if rate<=0: raise ValueError(f"rate>0 required, got {rate}")
        if capacity<=0: raise ValueError(f"capacity>0 required, got {capacity}")
        self._r=rate; self._cap=capacity; self._tok=capacity; self._last=time.monotonic(); self._lock:asyncio.Lock|None=None
    def _lk(self)->asyncio.Lock:
        if self._lock is None: self._lock=asyncio.Lock()
        return self._lock
    def _refill(self)->None:
        now=time.monotonic(); self._tok=min(self._cap,self._tok+(now-self._last)*self._r); self._last=now
    async def acquire(self,tokens:float=1.0)->float:
        async with self._lk():
            self._refill()
            if self._tok>=tokens: self._tok-=tokens; return 0.0
            wait=(tokens-self._tok)/self._r
        await asyncio.sleep(wait)
        async with self._lk(): self._refill(); self._tok-=tokens
        return wait
    @property
    def available(self)->float: self._refill(); return self._tok
    @property
    def rate(self)->float: return self._r
    @property
    def capacity(self)->float: return self._cap
class RateLimiter:
    def __init__(self,default_rate:float=1.0,default_burst:float|None=None)->None:
        if default_rate<=0: raise ValueError("default_rate must be positive")
        self._dr=default_rate; self._db=default_burst; self._b:dict[str,TokenBucket]={}; self._lock:asyncio.Lock|None=None
    def _lk(self)->asyncio.Lock:
        if self._lock is None: self._lock=asyncio.Lock()
        return self._lock
    def configure(self,domain:str,rate:float,burst:float|None=None)->None:
        self._b[domain]=TokenBucket(rate,burst or rate*2)
    def configure_from_meta(self,metas:list)->None:
        for m in metas:
            if getattr(m,"name",None) and getattr(m,"rate_limit_rps",None): self.configure(m.name,m.rate_limit_rps)
    async def acquire(self,domain:str,tokens:float=1.0)->float:
        async with self._lk():
            if domain not in self._b: self._b[domain]=TokenBucket(self._dr,self._db or self._dr*2)
        return await self._b[domain].acquire(tokens)
    def available(self,domain:str)->float: b=self._b.get(domain); return b.available if b else self._dr
    def stats(self)->dict: return {d:{"rate":b.rate,"available":b.available} for d,b in self._b.items()}
