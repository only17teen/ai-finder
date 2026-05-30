"""Asian dev-community collector: V2EX (CN), Qiita (JP), Zenn (JP).

These developer communities discuss niche AI tools long before they reach
Western directories. All expose clean JSON APIs. We pull AI-related posts and
extract external links from their bodies. Pure helpers are unit-tested.
"""
from __future__ import annotations

import asyncio
import re

from ..db import DB, Candidate, domain_of, is_noise_domain
from ..keywords import is_ai_related

PLATFORM = "asian_dev"
_URL_RE = re.compile(r"https?://[^\s\)\]\>\"'`]+")

V2EX_API = "https://www.v2ex.com/api/topics/latest.json"
QIITA_API = "https://qiita.com/api/v2/items?query=AI&per_page=40"
ZENN_API = "https://zenn.dev/api/articles?topicname=ai&order=latest"

_EXTRA_NOISE = {
    "v2ex.com", "qiita.com", "zenn.dev", "i.imgur.com", "imgur.com",
    "camo.qiitausercontent.com", "qiita-user-contents.imgix.net",
    "i.ibb.co", "ibb.co", "amazonaws.com", "qiita-image-store.s3.ap-northeast-1.amazonaws.com",
    "bilibili.com", "githubusercontent.com",
}

# Image/asset extensions — never a service homepage.
_ASSET_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4", ".pdf")


def _skip(domain: str) -> bool:
    if not domain or is_noise_domain(domain):
        return True
    return any(domain == d or domain.endswith("." + d) for d in _EXTRA_NOISE)


def extract_from_text(title: str, body: str, upvotes: int = 0) -> list[Candidate]:
    """Pure: AI-related external links from a post title+body."""
    if not is_ai_related(f"{title} {body}"):
        return []
    out, seen = [], set()
    for m in _URL_RE.finditer(body or ""):
        url = m.group(0).rstrip(".,;)")
        # reject malformed/markdown-mangled and asset urls
        if "<" in url or ">" in url or url.lower().endswith(_ASSET_EXT):
            continue
        dom = domain_of(url)
        if _skip(dom) or dom in seen:
            continue
        seen.add(dom)
        out.append(Candidate(url=url, name=(title or dom)[:80],
                             description=title[:160],
                             source_platform=PLATFORM, upvotes=upvotes))
    return out


async def fetch_candidates() -> list[Candidate]:
    from ..net import RateLimiter
    from ..net import fetch as _f
    limiter = RateLimiter(per_domain_delay=1.0)
    out: list[Candidate] = []
    async with httpx_client() as client:
        rv, rq, rz = await asyncio.gather(
            _f(client, V2EX_API, limiter=limiter),
            _f(client, QIITA_API, limiter=limiter),
            _f(client, ZENN_API, limiter=limiter),
        )
    if rv:
        try:
            for t in rv.json():
                out += extract_from_text(t.get("title", ""),
                                         t.get("content", ""),
                                         int(t.get("replies") or 0))
        except Exception:
            pass
    if rq:
        try:
            for a in rq.json():
                out += extract_from_text(a.get("title", ""), a.get("body", ""),
                                         int(a.get("likes_count") or 0))
        except Exception:
            pass
    if rz:
        try:
            for a in rz.json().get("articles", []):
                # Zenn bodies aren't in the list API; use title only.
                out += extract_from_text(a.get("title", ""), "",
                                         int(a.get("liked_count") or 0))
        except Exception:
            pass
    uniq: dict[str, Candidate] = {}
    for c in out:
        cur = uniq.get(c.domain)
        if not cur or c.upvotes > cur.upvotes:
            uniq[c.domain] = c
    return list(uniq.values())


def httpx_client():
    import httpx
    return httpx.AsyncClient(follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (ai-finder)"})


async def collect(db: DB) -> int:
    from . import store_candidates
    return store_candidates(db, PLATFORM, await fetch_candidates())


if __name__ == "__main__":
    async def _main():
        cands = await fetch_candidates()
        print(f"Found {len(cands)} Asian-dev AI candidates (V2EX/Qiita/Zenn):")
        for c in cands[:30]:
            print(f"  [{c.upvotes:>4}] {c.domain:<30} {c.name[:40]}")
    asyncio.run(_main())
