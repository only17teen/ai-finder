from __future__ import annotations
import asyncio,json as _j,logging
from typing import Any
log=logging.getLogger(__name__); UVLOOP_AVAILABLE=False
def install_uvloop()->bool:
    global UVLOOP_AVAILABLE
    if UVLOOP_AVAILABLE: return True
    try:
        import uvloop; asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        UVLOOP_AVAILABLE=True; return True
    except ImportError: return False
ORJSON_AVAILABLE=False
try:
    import orjson as _o  # type: ignore
    ORJSON_AVAILABLE=True
    def json_dumps(obj:Any,*,indent:bool=False)->str: return _o.dumps(obj,option=_o.OPT_INDENT_2 if indent else None).decode()
    def json_loads(data:str|bytes)->Any: return _o.loads(data)
except ImportError:
    def json_dumps(obj:Any,*,indent:bool=False)->str: return _j.dumps(obj,indent=2 if indent else None)
    def json_loads(data:str|bytes)->Any: return _j.loads(data.decode() if isinstance(data,bytes) else data)
