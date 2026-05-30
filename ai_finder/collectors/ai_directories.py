"""AI-directory collector (Playwright-rendered).

Directories like theresanaiforthat.com / toolify.ai / futurepedia.io list
thousands of AI tools. We render listing pages, extract outbound tool links,
and keep those whose context hints at an API. Parsing is pure and tested.
"""
from __future__ import annotations

import asyncio

from bs4 import BeautifulSoup

from ..db import DB, Candidate, domain_of
from ..keywords import is_ai_related, mentions_api
from ..browser import render

PLATFORM = "ai_directory"

SOURCES = [
    "https://theresanaiforthat.com/",
    "https://www.toolify.ai/",
    "https://www.futurepedia.io/",
]

# URL path fragments that mark a per-tool detail page on these directories.
_DETAIL_HINTS = ("/ai/", "/tool/", "/tools/", "/product/")

# Directory/infra domains that are never the discovered service itself.
_SELF = {"theresanaiforthat.com", "toolify.ai", "futurepedia.io"}
_NOISE = {
    "google.com", "youtube.com", "twitter.com", "x.com", "facebook.com",
    "linkedin.com", "instagram.com", "github.com", "discord.com",
    "discord.gg", "apple.com", "play.google.com",
    "getrewardful.com", "rewardful.com", "promotekit.com",
}


def _skip(domain: str, src_domain: str) -> bool:
    if not domain or domain == src_domain:
        return True
    return any(domain == d or domain.endswith("." + d)
               for d in _SELF | _NOISE)


def extract_detail_links(html: str, source_url: str) -> list[str]:
    """Pure: same-domain per-tool detail-page URLs found on a listing page."""
    from urllib.parse import urljoin
    src_domain = domain_of(source_url)
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(source_url, a["href"].strip())
        if domain_of(href) != src_domain:
            continue
        if not any(h in href.lower() for h in _DETAIL_HINTS):
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append(href)
    return out


def extract_outbound(html: str, source_url: str) -> Candidate | None:
    """Pure: the external tool link from a detail page (first non-noise host).

    Prefers anchors whose text says visit/website/try/open.
    """
    src_domain = domain_of(source_url)
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(strip=True) if soup.title else "")
    prefer, fallback = None, None
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith("http"):
            continue
        if _skip(domain_of(href), src_domain):
            continue
        text = a.get_text(" ", strip=True).lower()
        if any(w in text for w in ("visit", "website", "try", "open", "go to")):
            prefer = href
            break
        fallback = fallback or href
    url = prefer or fallback
    if not url:
        return None
    return Candidate(url=url, name=title[:80] or domain_of(url),
                     description=title[:180], source_platform=PLATFORM)


def extract_candidates(html: str, source_url: str) -> list[Candidate]:
    """Pure: extract AI-tool links from a rendered directory page.

    Keeps links whose anchor/context is AI-related; flags API hints in name.
    """
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
        ctx = f"{anchor} {parent}"
        if not is_ai_related(ctx):
            continue
        seen.add(dom)
        out.append(Candidate(
            url=href,
            name=anchor[:80] or dom,
            description=("[api hint] " if mentions_api(ctx) else "") + parent[:180],
            source_platform=PLATFORM,
        ))
    return out


async def fetch_candidates(sources: list[str] | None = None,
                           max_details: int = 20) -> list[Candidate]:
    """Two-level crawl: listing -> detail pages -> outbound tool sites.

    Also keeps any direct outbound links found on the listing itself.
    `max_details` bounds how many detail pages are rendered per source.
    """
    sources = sources or SOURCES
    out: list[Candidate] = []
    for url in sources:
        html = await render(url)
        if not html:
            continue
        # Fast pass: direct outbound links on the listing.
        out.extend(extract_candidates(html, url))
        # Deep pass: render per-tool detail pages, pull their outbound link.
        details = extract_detail_links(html, url)[:max_details]
        rendered = await asyncio.gather(*[render(d) for d in details])
        for detail_url, dhtml in zip(details, rendered):
            if not dhtml:
                continue
            c = extract_outbound(dhtml, detail_url)
            if c and c.domain:
                out.append(c)
    uniq: dict[str, Candidate] = {}
    for c in out:
        uniq.setdefault(c.domain, c)
    return list(uniq.values())


async def collect(db: DB, sources: list[str] | None = None) -> int:
    cands = await fetch_candidates(sources)
    new = sum(db.upsert_candidate(c)[1] for c in cands)
    db.log_source(PLATFORM, len(cands), new)
    return new


if __name__ == "__main__":
    async def _main():
        cands = await fetch_candidates()
        print(f"Found {len(cands)} AI-tool links across directories:")
        for c in cands[:20]:
            print(f"  {c.domain:<30} {c.name[:45]}")
    asyncio.run(_main())
