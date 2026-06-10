"""Reddit collector via public RSS (bypasses the JSON API block).

Niche AI subreddits (LocalLLaMA, selfhosted, StableDiffusion, ...) surface
brand-new tools daily. We read each subreddit's `new.rss`, extract external
links from post content, and keep AI-related ones. Pure parser is unit-tested.
"""

from __future__ import annotations

import asyncio
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from ..db import DB, Candidate, domain_of, is_noise_domain
from ..keywords import is_ai_related

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

PLATFORM = "reddit"

SUBREDDITS = [
    "LocalLLaMA",
    "selfhosted",
    "StableDiffusion",
    "artificial",
    "MachineLearning",
    "OpenAI",
    "ArtificialIntelligence",
    "ollama",
    "comfyui",
    "LLMDevs",
]
RSS = "https://www.reddit.com/r/{sub}/new.rss?limit=100"

_ASSET_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".pdf")
_EXTRA_NOISE = {
    "reddit.com",
    "redd.it",
    "preview.redd.it",
    "i.redd.it",
    "v.redd.it",
    "external-preview.redd.it",
}


def _skip(domain: str) -> bool:
    if not domain or is_noise_domain(domain):
        return True
    return any(domain == d or domain.endswith("." + d) for d in _EXTRA_NOISE)


def extract_from_rss(xml: str) -> list[Candidate]:
    """Pure: AI-related external links from a subreddit Atom RSS feed."""
    soup = BeautifulSoup(xml, "html.parser")
    out: list[Candidate] = []
    seen: set[str] = set()
    for entry in soup.find_all("entry"):
        title_el = entry.find("title")
        title = title_el.get_text(strip=True) if title_el else ""
        content = entry.find("content")
        inner = BeautifulSoup(content.get_text(), "html.parser") if content else None
        body_text = inner.get_text(" ", strip=True) if inner else ""
        if not is_ai_related(f"{title} {body_text}"):
            continue
        links = inner.find_all("a", href=True) if inner else []
        for a in links:
            href = a["href"].strip()
            if not href.startswith("http") or href.lower().endswith(_ASSET_EXT):
                continue
            dom = domain_of(href)
            if _skip(dom) or dom in seen:
                continue
            seen.add(dom)
            out.append(
                Candidate(
                    url=href,
                    name=title[:80] or dom,
                    description=title[:160],
                    source_platform=PLATFORM,
                )
            )
    return out


async def fetch_candidates(subreddits: list[str] | None = None) -> list[Candidate]:
    import httpx

    from ..net import RateLimiter, fetch

    subs = subreddits or SUBREDDITS
    limiter = RateLimiter(per_domain_delay=2.0)  # be polite to reddit
    urls = [RSS.format(sub=s) for s in subs]
    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": "linux:ai-finder:1.0 (research)"},
    ) as client:
        responses = await asyncio.gather(*[fetch(client, u, limiter=limiter) for u in urls])
    out: list[Candidate] = []
    for r in responses:
        if r:
            out.extend(extract_from_rss(r.text))
    from ._base import dedup_by_domain

    return dedup_by_domain(out)


async def collect(db: DB, subreddits: list[str] | None = None) -> int:
    from . import store_candidates

    return store_candidates(db, PLATFORM, await fetch_candidates(subreddits))


if __name__ == "__main__":

    async def _main():
        cands = await fetch_candidates()
        print(f"Found {len(cands)} Reddit AI candidates:")
        for c in cands[:30]:
            print(f"  {c.domain:<30} {c.name[:42]}")

    asyncio.run(_main())
