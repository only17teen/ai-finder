"""Launch-platform collector: ultra-early indie launch sites.

MicroLaunch / TinyLaunch list brand-new indie products days after creation —
long before they hit ProductHunt or directories. Server-rendered; we keep
AI-related outbound links. Parsing is pure and unit-tested.
"""
from __future__ import annotations

import asyncio

from bs4 import BeautifulSoup

from ..db import DB, Candidate, domain_of, is_noise_domain
from ..keywords import is_ai_related

PLATFORM = "launch"

SOURCES = [
    "https://microlaunch.net/",
    "https://www.tinylaunch.com/",
]

_SELF = {"microlaunch.net", "tinylaunch.com"}


def _skip(domain: str, src_domain: str) -> bool:
    if not domain or domain == src_domain or is_noise_domain(domain):
        return True
    return any(domain == d or domain.endswith("." + d) for d in _SELF)


def extract_candidates(html: str, source_url: str) -> list[Candidate]:
    """Pure: AI-related external launch links from a launch-platform page."""
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
    from ..net import fetch_all
    out: list[Candidate] = []
    responses = await fetch_all(SOURCES)
    for url, r in zip(SOURCES, responses):
        if r:
            out.extend(extract_candidates(r.text, url))
    uniq: dict[str, Candidate] = {}
    for c in out:
        uniq.setdefault(c.domain, c)
    return list(uniq.values())


async def collect(db: DB) -> int:
    cands = await fetch_candidates()
    new = sum(db.upsert_candidate(c)[1] for c in cands)
    db.log_source(PLATFORM, len(cands), new)
    return new


if __name__ == "__main__":
    async def _main():
        cands = await fetch_candidates()
        print(f"Found {len(cands)} early-launch AI candidates:")
        for c in cands[:30]:
            print(f"  {c.domain:<30} {c.name[:40]}")
    asyncio.run(_main())
