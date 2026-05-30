"""Mastodon collector: AI-hashtag timelines from public instances.

Federated, no auth. We read each instance's #ai tag timeline and keep the
link-preview cards (`card.url`) — the actual external services people share.
Card mapping is pure and unit-tested.
"""
from __future__ import annotations

import asyncio

from ..db import DB, Candidate, domain_of, is_noise_domain
from ..keywords import is_ai_related

PLATFORM = "mastodon"

INSTANCES = ["mastodon.social", "hachyderm.io", "mas.to"]
TAG_URL = "https://{inst}/api/v1/timelines/tag/ai?limit=40"

# Mastodon hosts + link shorteners are not the discovered service.
_EXTRA_NOISE = {
    "mastodon.social", "mastodon.uno", "mastodon.online", "mas.to",
    "hachyderm.io", "mstdn.social", "bit.ly", "buff.ly", "t.co", "ow.ly",
    "tinyurl.com", "dlvr.it", "flip.it", "podbean.com",
}


def card_to_candidate(card: dict) -> Candidate | None:
    """Pure: map a toot's link-preview card to a Candidate (AI-related only)."""
    if not card:
        return None
    url = card.get("url")
    if not url:
        return None
    title = card.get("title") or ""
    desc = card.get("description") or ""
    dom = domain_of(url)
    if not dom or is_noise_domain(dom):
        return None
    if any(dom == d or dom.endswith("." + d) for d in _EXTRA_NOISE):
        return None
    if not is_ai_related(f"{title} {desc}"):
        return None
    return Candidate(url=url, name=title[:80] or dom,
                     description=desc[:160], source_platform=PLATFORM)


async def fetch_candidates() -> list[Candidate]:
    from ..net import fetch_all
    urls = [TAG_URL.format(inst=i) for i in INSTANCES]
    responses = await fetch_all(urls, per_domain_delay=1.0)
    out: list[Candidate] = []
    for r in responses:
        if not r:
            continue
        try:
            toots = r.json()
        except Exception:
            continue
        for t in toots:
            c = card_to_candidate(t.get("card"))
            if c:
                out.append(c)
    uniq: dict[str, Candidate] = {}
    for c in out:
        uniq.setdefault(c.domain, c)
    return list(uniq.values())


async def collect(db: DB) -> int:
    from . import store_candidates
    return store_candidates(db, PLATFORM, await fetch_candidates())


if __name__ == "__main__":
    async def _main():
        cands = await fetch_candidates()
        print(f"Found {len(cands)} Mastodon #ai card candidates:")
        for c in cands[:30]:
            print(f"  {c.domain:<30} {c.name[:40]}")
    asyncio.run(_main())
