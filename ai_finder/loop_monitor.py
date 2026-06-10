from __future__ import annotations
import asyncio,logging,os,time
log=logging.getLogger(__name__)
_W=float(os.getenv("LOOP_WARN_MS","50"))/1000
_C=float(os.getenv("LOOP_CRITICAL_MS","100"))/1000
async def monitor_event_loop(interval:float=1.0)->None:
    while True:
        t0=time.monotonic(); await asyncio.sleep(interval); lag=(time.monotonic()-t0-interval)*1000
        if lag/1000>_C: log.critical("LOOP_CRITICAL_LAG lag_ms=%.1f",lag)
        elif lag/1000>_W: log.warning("LOOP_SLOW lag_ms=%.1f",lag)
