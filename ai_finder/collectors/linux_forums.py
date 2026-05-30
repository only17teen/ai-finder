"""Linux-forum collector (httpx + BeautifulSoup).

Strategy: fetch forum thread/listing pages, then keep *external* links whose
anchor text or surrounding context mentions AI. Forum-internal and well-known
infra/social links are ignored. The HTML parser is pure and unit-tested; the
live fetch is best-effort (forums vary and may rate-limit).
"""
from __future__ import annotations

import asyncio

from bs4 import BeautifulSoup

from ..db import DB, Candidate
from ..keywords import is_ai_related

PLATFORM = "linux_forum"

# (name, page_url) — public listing/search pages likely to mention AI tools.
SOURCES: list[tuple[str, str]] = [
    ("lwn", "https://lwn.net/"),
    ("phoronix", "https://www.phoronix.com/"),
    ("itsfoss", "https://news.itsfoss.com/"),
]

# Domains we never treat as discovered services.
NOISE = {
    "google.com", "youtube.com", "twitter.com", "x.com", "facebook.com",
    "linkedin.com", "reddit.com", "wikipedia.org", "archive.org",
    "patreon.com", "paypal.com", "amazon.com", "apple.com", "mozilla.org",
}


def _is_noise(domain: str, forum_domain: str) -> bool:
    if not domain or domain == forum_domain or domain.endswith("." + forum_domain):
        return True
    return any(domain == n or domain.endswith("." + n) for n in NOISE)


def extract_candidates(html: str, forum_url: str) -> list[Candidate]:
    """Pure: pull AI-related external links out of a forum page."""
    from ..db import domain_of
    forum_domain = domain_of(forum_url)
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    out: list[Candidate] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith("http"):
            continue
        dom = domain_of(href)
        if _is_noise(dom, forum_domain) or dom in seen:
            continue
        # context = anchor text + parent text (captures "great AI tool: <link>")
        anchor = a.get_text(" ", strip=True)
        parent = a.parent.get_text(" ", strip=True) if a.parent else ""
        if not (is_ai_related(anchor) or is_ai_related(parent)):
            continue
        seen.add(dom)
        out.append(Candidate(
            url=href,
            name=anchor[:80] or dom,
            description=parent[:200],
            source_platform=PLATFORM,
        ))
    return out


async def fetch_candidates() -> list[Candidate]:
    from ..net import fetch_all
    urls = [url for _name, url in SOURCES]
    responses = await fetch_all(urls)
    out: list[Candidate] = []
    for url, r in zip(urls, responses):
        if r:
            out.extend(extract_candidates(r.text, url))
    # dedup across forums by domain
    uniq: dict[str, Candidate] = {}
    for c in out:
        uniq.setdefault(c.domain, c)
    return [c for c in uniq.values() if c.domain]


async def collect(db: DB) -> int:
    from . import store_candidates
    return store_candidates(db, PLATFORM, await fetch_candidates())


if __name__ == "__main__":
    async def _main():
        cands = await fetch_candidates()
        print(f"Found {len(cands)} external AI links across Linux forums:")
        for c in cands[:20]:
            print(f"  {c.domain:<30} {c.name[:50]}")
    asyncio.run(_main())
