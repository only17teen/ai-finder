"""HackerNews 'Show HN' collector via the official Firebase API.

Free, no key, no rate limit. We read Show HN stories, keep AI-related ones
that link to an external site, and store them as candidates.
"""
from __future__ import annotations

import asyncio

import httpx

from ..db import DB, Candidate
from ..keywords import is_ai_related

BASE = "https://hacker-news.firebaseio.com/v0"
PLATFORM = "hackernews"


def story_to_candidate(item: dict) -> Candidate | None:
    """Convert an HN item to a Candidate, or None if not a usable lead.

    Pure function — no network. Keeps AI-related external-link stories.
    """
    if not item or item.get("type") != "story":
        return None
    url = item.get("url")
    if not url:  # text-only Ask HN etc. — no external service to verify
        return None
    title = item.get("title", "")
    if not is_ai_related(title):
        return None
    return Candidate(
        url=url,
        name=title.replace("Show HN:", "").strip(),
        description=title,
        source_platform=PLATFORM,
        upvotes=int(item.get("score", 0) or 0),
    )


async def _fetch_json(client: httpx.AsyncClient, url: str):
    r = await client.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


async def fetch_candidates(limit: int = 100) -> list[Candidate]:
    """Fetch up to `limit` Show HN stories and return AI candidates."""
    async with httpx.AsyncClient() as client:
        ids = await _fetch_json(client, f"{BASE}/showstories.json")
        ids = (ids or [])[:limit]
        items = await asyncio.gather(
            *[_fetch_json(client, f"{BASE}/item/{i}.json") for i in ids],
            return_exceptions=True,
        )
    out = []
    for it in items:
        if isinstance(it, Exception):
            continue
        c = story_to_candidate(it)
        if c and c.domain:
            out.append(c)
    return out


async def collect(db: DB, limit: int = 100) -> int:
    """Fetch and store candidates. Returns count of new services."""
    cands = await fetch_candidates(limit)
    new = sum(db.upsert_candidate(c)[1] for c in cands)
    db.log_source(PLATFORM, len(cands), new)
    return new


if __name__ == "__main__":
    async def _main():
        cands = await fetch_candidates(60)
        print(f"Found {len(cands)} AI candidates on Show HN:")
        for c in cands[:15]:
            print(f"  [{c.upvotes:>4}] {c.domain:<28} {c.name[:50]}")
    asyncio.run(_main())
