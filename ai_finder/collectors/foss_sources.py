"""FOSS / Linux / self-hosted niche-source collector.

Mines communities and lists the mainstream AI-tool crowd ignores:
- Lobsters (lobste.rs) — tech link aggregator, AI tag
- Slashdot — long-running nerd news
- Hacker News "newest" + Algolia keyword API (catches brand-new launches)
- awesome-selfhosted style lists (self-hosted / local-LLM tooling)

All HTML/JSON — no browser. Parsing helpers are pure and unit-tested.
"""
from __future__ import annotations

import asyncio

from bs4 import BeautifulSoup

from ..db import DB, Candidate, domain_of, is_noise_domain
from ..keywords import is_ai_related

PLATFORM = "foss"

# Server-rendered link aggregators (story links point outward).
HTML_SOURCES = [
    "https://lobste.rs/t/ai",        # Lobsters AI tag
    "https://slashdot.org/",         # Slashdot front
    "https://news.ycombinator.com/newest",  # HN brand-new submissions
]

# Raw awesome-list READMEs (self-hosted / local-LLM ecosystems).
LIST_SOURCES = [
    "https://raw.githubusercontent.com/vince-lam/awesome-local-llms/main/README.md",
]

# HN Algolia keyword search — recent AI stories with external links.
ALGOLIA = ("https://hn.algolia.com/api/v1/search_by_date"
           "?query=AI%20API&tags=story&hitsPerPage=60")

_EXTRA_NOISE = {
    "lobste.rs", "slashdot.org", "news.ycombinator.com", "ycombinator.com",
    "raw.githubusercontent.com", "githubusercontent.com", "archive.org",
    "ko-fi.com", "patreon.com", "hn.algolia.com",
}


def _skip(domain: str, src_domain: str) -> bool:
    if not domain or domain == src_domain or is_noise_domain(domain):
        return True
    return any(domain == d or domain.endswith("." + d) for d in _EXTRA_NOISE)


def extract_links(html: str, source_url: str) -> list[Candidate]:
    """Pure: AI-related external links from an aggregator/list page."""
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


def algolia_hit_to_candidate(hit: dict) -> Candidate | None:
    """Pure: map an HN Algolia story hit to a Candidate (AI external link)."""
    url = hit.get("url")
    title = hit.get("title") or ""
    if not url or not is_ai_related(title):
        return None
    c = Candidate(url=url, name=title[:80], description=title[:160],
                  source_platform=PLATFORM,
                  upvotes=int(hit.get("points") or 0))
    return c if c.domain and not is_noise_domain(c.domain) else None


async def fetch_candidates() -> list[Candidate]:
    from ..net import fetch_all
    html_urls = HTML_SOURCES + LIST_SOURCES
    responses = await fetch_all(html_urls + [ALGOLIA])
    out: list[Candidate] = []
    for url, r in zip(html_urls, responses):
        if r:
            out.extend(extract_links(r.text, url))
    algolia_resp = responses[-1]
    if algolia_resp:
        try:
            for hit in algolia_resp.json().get("hits", []):
                c = algolia_hit_to_candidate(hit)
                if c:
                    out.append(c)
        except Exception:
            pass
    uniq: dict[str, Candidate] = {}
    for c in out:
        if c.domain:
            cur = uniq.get(c.domain)
            if not cur or c.upvotes > cur.upvotes:
                uniq[c.domain] = c
    return list(uniq.values())


async def collect(db: DB) -> int:
    from . import store_candidates
    return store_candidates(db, PLATFORM, await fetch_candidates())


if __name__ == "__main__":
    async def _main():
        cands = await fetch_candidates()
        print(f"Found {len(cands)} FOSS/Linux/self-hosted AI candidates:")
        for c in cands[:30]:
            print(f"  [{c.upvotes:>4}] {c.domain:<30} {c.name[:40]}")
    asyncio.run(_main())
