from __future__ import annotations
import hashlib,re
from urllib.parse import parse_qsl,urlencode,urlparse,urlunparse
_T=frozenset({"utm_source","utm_medium","utm_campaign","utm_content","utm_term","utm_id",
    "fbclid","gclid","msclkid","twclid","ref","referrer","source","from","via","_hsenc","mc_cid","mc_eid"})
def canonical_url(url:str)->str:
    url=url.strip()
    if not url: return url
    if not re.match(r"^https?://",url,re.I): url="https://"+url
    try:
        p=urlparse(url); scheme=(p.scheme or "https").lower(); host=p.netloc.lower()
        if host.startswith("www."): host=host[4:]
        if ":" in host:
            h,_,port=host.rpartition(":")
            if (scheme=="http" and port=="80") or (scheme=="https" and port=="443"): host=h
        path=p.path.rstrip("/"  ) or "/"
        query=urlencode(sorted((k,v) for k,v in parse_qsl(p.query) if k.lower() not in _T))
        return urlunparse((scheme,host,path,p.params,query,""))
    except Exception: return url.lower().strip()
def fingerprint_url(url:str)->str: return hashlib.sha256(canonical_url(url).encode()).hexdigest()
def domain_of(url:str)->str:
    try: return urlparse(url.strip()).netloc.lower().lstrip("www.").split(":")[0]
    except Exception: return url.lower().strip()
