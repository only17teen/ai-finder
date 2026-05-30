"""Niche-forum collector: Lemmy (federated FOSS) + dev.to.

Lemmy instances host self-hosted/FOSS communities the mainstream crowd ignores;
their JSON API exposes post URLs. dev.to has a clean articles API tagged 'ai'.
Both JSON — fast, no browser. Mapping helpers are pure and unit-tested.
"""
from __future__ import annotations

import asyncio

import httpx

from ..db import DB, Candidate, is_noise_domain
from ..keywords import is_ai_related

PLATFORM = "forums"

# Lemmy instances (federated). Public search API, no auth.
LEMMY_INSTANCES = ["lemmy.world", "programming.dev", "lemmy.ml",
                   "lemmy.dbzer0.com", "sh.itjust.works", "feddit.org"]
LEMMY_SEARCH = ("https://{inst}/api/v3/search"
                "?q=AI&type_=Posts&sort=New&limit=40")

DEVTO_API = "https://dev.to/api/articles?tag=ai&per_page=60"


def lemmy_post_to_candidate(post_view: dict) -> Candidate | None:
    """Pure: map a Lemmy post view to a Candidate (external AI link only)."""
    post = post_view.get("post", {}) if isinstance(post_view, dict) else {}
    url = post.get("url")
    name = post.get("name", "")  # Lemmy 'name' is the title
    if not url or not (is_ai_related(name) or is_ai_related(post.get("body", ""))):
        return None
    score = 0
    counts = post_view.get("counts", {})
    if isinstance(counts, dict):
        score = int(counts.get("score") or 0)
    c = Candidate(url=url, name=name[:80], description=name[:160],
                  source_platform=PLATFORM, upvotes=score)
    return c if c.domain and not is_noise_domain(c.domain) else None


def devto_article_to_candidate(art: dict) -> Candidate | None:
    """Pure: map a dev.to article to a Candidate (skips dev.to-hosted posts)."""
    url = art.get("canonical_url") or art.get("url")
    title = art.get("title", "")
    if not url:
        return None
    c = Candidate(url=url, name=title[:80],
                  description=(art.get("description") or "")[:160],
                  source_platform=PLATFORM,
                  upvotes=int(art.get("positive_reactions_count") or 0))
    # dev.to canonical often points back to dev.to — drop those + noise.
    if not c.domain or c.domain == "dev.to" or is_noise_domain(c.domain):
        return None
    if not (is_ai_related(title) or is_ai_related(c.description)):
        return None
    return c


async def fetch_candidates() -> list[Candidate]:
    from ..net import RateLimiter, fetch
    limiter = RateLimiter(per_domain_delay=1.0)
    out: list[Candidate] = []
    async with httpx.AsyncClient(follow_redirects=True) as client:
        # All instances + dev.to fetched concurrently.
        urls = [LEMMY_SEARCH.format(inst=i) for i in LEMMY_INSTANCES] + [DEVTO_API]
        responses = await asyncio.gather(
            *[fetch(client, u, limiter=limiter) for u in urls])
    for url, r in zip(urls, responses):
        if not r:
            continue
        try:
            data = r.json()
        except Exception:
            continue
        if "dev.to" in url:
            for art in data:
                c = devto_article_to_candidate(art)
                if c:
                    out.append(c)
        else:
            for pv in data.get("posts", []):
                c = lemmy_post_to_candidate(pv)
                if c:
                    out.append(c)
    from ._base import dedup_by_domain
    return dedup_by_domain(out, prefer_higher_upvotes=True)


async def collect(db: DB) -> int:
    from . import store_candidates
    return store_candidates(db, PLATFORM, await fetch_candidates())


if __name__ == "__main__":
    async def _main():
        cands = await fetch_candidates()
        print(f"Found {len(cands)} forum AI candidates (Lemmy + dev.to):")
        for c in cands[:30]:
            print(f"  [{c.upvotes:>4}] {c.domain:<30} {c.name[:40]}")
    asyncio.run(_main())
