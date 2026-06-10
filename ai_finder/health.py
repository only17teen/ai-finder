from __future__ import annotations
import asyncio,enum,logging,os,shutil,sqlite3,time
from dataclasses import dataclass,field
from typing import Any,Protocol,runtime_checkable
log=logging.getLogger(__name__)
class HealthStatus(str,enum.Enum):
    HEALTHY="healthy"; DEGRADED="degraded"; UNHEALTHY="unhealthy"
@dataclass
class HealthResult:
    name:str; status:HealthStatus; message:str=""; duration_ms:float=0.0; details:dict[str,Any]=field(default_factory=dict)
@runtime_checkable
class HealthCheck(Protocol):
    name:str
    async def check(self)->HealthResult: ...
class HealthRegistry:
    def __init__(self,timeout:float=5.0)->None: self._ch:dict[str,HealthCheck]={}; self._to=timeout
    def register(self,c:HealthCheck)->"HealthRegistry": self._ch[c.name]=c; return self
    def deregister(self,n:str)->None: self._ch.pop(n,None)
    async def check_all(self)->list[HealthResult]:
        if not self._ch: return []
        async def _s(c:HealthCheck)->HealthResult:
            t0=time.perf_counter()
            try:
                r=await asyncio.wait_for(c.check(),timeout=self._to); r.duration_ms=(time.perf_counter()-t0)*1000; return r
            except asyncio.TimeoutError: return HealthResult(c.name,HealthStatus.UNHEALTHY,f"Timeout {self._to:.0f}s",(time.perf_counter()-t0)*1000)
            except Exception as e: return HealthResult(c.name,HealthStatus.UNHEALTHY,str(e),(time.perf_counter()-t0)*1000)
        return list(await asyncio.gather(*[_s(c) for c in self._ch.values()]))
    @staticmethod
    def aggregate(rs:list[HealthResult])->HealthStatus:
        if any(r.status==HealthStatus.UNHEALTHY for r in rs): return HealthStatus.UNHEALTHY
        if any(r.status==HealthStatus.DEGRADED for r in rs): return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY
    def names(self)->list[str]: return list(self._ch)
class DBHealthCheck:
    name="database"
    def __init__(self,db_path:str="ai_finder.db")->None: self._db=db_path
    async def check(self)->HealthResult:
        try:
            await asyncio.get_running_loop().run_in_executor(None,lambda:sqlite3.connect(self._db,timeout=2).execute("SELECT 1"))
            return HealthResult(self.name,HealthStatus.HEALTHY,"ok",details={"path":self._db})
        except Exception as e: return HealthResult(self.name,HealthStatus.UNHEALTHY,str(e))
class DiskSpaceCheck:
    name="disk_space"
    def __init__(self,db_path:str="ai_finder.db",min_free_mb:float=100.0)->None:
        self._path=str(os.path.dirname(os.path.abspath(db_path)) or "."); self._min=min_free_mb
    async def check(self)->HealthResult:
        try:
            u=shutil.disk_usage(self._path); free=u.free/(1024*1024); pct=100*u.used/u.total; d={"free_mb":round(free,1),"pct":round(pct,1)}
            if free<self._min: return HealthResult(self.name,HealthStatus.UNHEALTHY,f"{free:.0f}MB free",details=d)
            if pct>85: return HealthResult(self.name,HealthStatus.DEGRADED,f"Disk {pct:.0f}%",details=d)
            return HealthResult(self.name,HealthStatus.HEALTHY,f"{free:.0f}MB free",details=d)
        except Exception as e: return HealthResult(self.name,HealthStatus.UNHEALTHY,str(e))
class LoopLagCheck:
    name="event_loop"
    def __init__(self,probe_s:float=0.01,warn_ms:float=50.0,crit_ms:float=100.0)->None:
        self._p=probe_s; self._w=warn_ms/1000; self._c=crit_ms/1000
    async def check(self)->HealthResult:
        t0=time.monotonic(); await asyncio.sleep(self._p); lag=time.monotonic()-t0-self._p; ms=lag*1000; d={"lag_ms":round(ms,2)}
        if lag>self._c: return HealthResult(self.name,HealthStatus.UNHEALTHY,f"Critical {ms:.1f}ms",details=d)
        if lag>self._w: return HealthResult(self.name,HealthStatus.DEGRADED,f"Elevated {ms:.1f}ms",details=d)
        return HealthResult(self.name,HealthStatus.HEALTHY,f"{ms:.1f}ms",details=d)
_reg:HealthRegistry|None=None
def get_health_registry()->HealthRegistry:
    global _reg
    if _reg is None: _reg=HealthRegistry(); _reg.register(DBHealthCheck()); _reg.register(DiskSpaceCheck()); _reg.register(LoopLagCheck())
    return _reg
