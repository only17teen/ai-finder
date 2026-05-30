"""ProductHunt + IndieHackers collector via Apify actors.

JS-heavy sites — we delegate rendering to Apify actors and read their dataset.
Actor ids are configurable; item->Candidate mapping is pure and tested.
Requires an Apify token (config/env); without one, collection is skipped.
"""
from __future__ import annotations

import asyncio
import os

from ..db import DB, Candidate
from ..keywords import is_ai_related

PLATFORM_PH = "producthunt"
PLATFORM_IH = "indiehackers"

# Default public actors (overridable via config).
DEFAULT_ACTORS = {
    PLATFORM_PH: "red.cars/producthunt-scraper",
    PLATFORM_IH: "cryptosignals/indiehackers-scraper",
}

# Keys an actor item may use for each field (first present wins).
_URL_KEYS = ("website", "websiteUrl", "url", "link", "productUrl", "homepage")
_NAME_KEYS = ("name", "title", "productName", "product")
_DESC_KEYS = ("description", "tagline", "summary", "text", "subtitle")
_VOTE_KEYS = ("votesCount", "votes", "upvotes", "points", "score")


def _first(item: dict, keys) -> str:
    for k in keys:
        v = item.get(k)
        if v:
            return v if isinstance(v, str) else str(v)
    return ""


def item_to_candidate(item: dict, platform: str) -> Candidate | None:
    """Pure: map an Apify dataset item to a Candidate (AI-filtered)."""
    url = _first(item, _URL_KEYS)
    if not url:
        return None
    name = _first(item, _NAME_KEYS)
    desc = _first(item, _DESC_KEYS)
    if not (is_ai_related(name) or is_ai_related(desc)):
        return None
    votes = 0
    for k in _VOTE_KEYS:
        try:
            votes = int(item.get(k) or 0)
            if votes:
                break
        except (TypeError, ValueError):
            continue
    c = Candidate(url=url, name=name, description=desc,
                  source_platform=platform, upvotes=votes)
    return c if c.domain else None


def _run_actor(token: str, actor: str, run_input: dict) -> list[dict]:
    """Run an Apify actor synchronously and return its dataset items."""
    from apify_client import ApifyClient
    client = ApifyClient(token)
    run = client.actor(actor).call(run_input=run_input)
    if not run:
        return []
    return list(client.dataset(run["defaultDatasetId"]).iterate_items())


async def fetch_candidates(
    token: str | None = None,
    actors: dict | None = None,
    run_input: dict | None = None,
) -> list[Candidate]:
    token = token or os.getenv("APIFY_TOKEN")
    if not token:
        return []
    actors = actors or DEFAULT_ACTORS
    run_input = run_input or {"maxItems": 100}
    out: list[Candidate] = []
    for platform, actor in actors.items():
        try:
            items = await asyncio.to_thread(_run_actor, token, actor, run_input)
        except Exception:
            continue
        for it in items:
            c = item_to_candidate(it, platform)
            if c:
                out.append(c)
    return out


async def collect(db: DB, token: str | None = None,
                  actors: dict | None = None) -> int:
    cands = await fetch_candidates(token, actors)
    new = sum(db.upsert_candidate(c)[1] for c in cands)
    db.log_source("apify", len(cands), new)
    return new


if __name__ == "__main__":
    async def _main():
        if not os.getenv("APIFY_TOKEN"):
            print("APIFY_TOKEN not set — set it to run live. Mapping demo:")
            sample = {"name": "GeekAI", "website": "https://geekai.co",
                      "tagline": "LLM gateway API", "votesCount": 120}
            print(" ", item_to_candidate(sample, PLATFORM_PH))
            return
        cands = await fetch_candidates()
        print(f"Found {len(cands)} AI products via Apify:")
        for c in cands[:20]:
            print(f"  [{c.upvotes:>4}] {c.domain:<28} {c.name[:50]}")
    asyncio.run(_main())
