"""International-community collector: Korean GeekNews (news.hada.io).

GeekNews is Korea's "Hacker News" — server-rendered, links out to the tools and
projects Korean developers discuss before they reach Western directories. We
keep AI-related external links. Parsing is pure and unit-tested.
"""
from __future__ import annotations

import asyncio

from bs4 import BeautifulSoup

from ..db import DB, Candidate, domain_of, is_noise_domain
from ..keywords import is_ai_related

PLATFORM = "intl_forums"

SOURCES = [
    "https://news.hada.io/",          # 🇰🇷 GeekNews front
    "https://news.hada.io/new",       # 🇰🇷 GeekNews newest
]
_SELF = {"news.hada.io", "hada.io"}


def _skip(domain: str, src_domain: str) -> bool:
    if not domain or domain == src_domain or is_noise_domain(domain):
        return True
    return any(domain == d or domain.endswith("." + d) for d in _SELF)


def extract_candidates(html: str, source_url: str) -> list[Candidate]:
    """Pure: AI-related external links from a GeekNews listing page."""
    src_domain = domain_of(source_url)
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    out: list[Candidate] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith("http"):
            continue
        dom = domain_of(href)
        if _skip(dom, src_domain) or dom in seen:
            continue
        anchor = a.get_text(" ", strip=True)
        parent = a.parent.get_text(" ", strip=True) if a.parent else ""
        if not (is_ai_related(anchor) or is_ai_related(parent)):
            continue
        seen.add(dom)
        out.append(Candidate(url=href, name=(anchor or dom)[:80],
                             description=parent[:160], source_platform=PLATFORM))
    return out


async def fetch_candidates() -> list[Candidate]:
    from ._base import html_collect
    return await html_collect(SOURCES, extract_candidates, stealth_fallback=True)


async def collect(db: DB) -> int:
    from . import store_candidates
    return store_candidates(db, PLATFORM, await fetch_candidates())


if __name__ == "__main__":
    async def _main():
        cands = await fetch_candidates()
        print(f"Found {len(cands)} Korean GeekNews AI candidates:")
        for c in cands[:30]:
            print(f"  {c.domain:<30} {c.name[:40]}")
    asyncio.run(_main())
