"""linux.do collector — Chinese Discourse tech community.

linux.do is a busy Chinese developer forum where niche AI services (and their
invite/registration links) get shared constantly. It sits behind Cloudflare, so
we render its public Discourse JSON via Playwright, pick AI-related topics, then
pull external service links out of each topic's posts. Parsing is pure/tested;
only public content is read.

NOTE: Cloudflare frequently challenges headless browsers, so live runs may
return nothing until a render slips through. For reliable access, point a
stealth browser / residential proxy at the same JSON endpoints — the parsing
below is independent of how the HTML was fetched.
"""
from __future__ import annotations

import asyncio
import json
import re

from bs4 import BeautifulSoup

from ..db import DB, Candidate, domain_of, is_noise_domain
from ..keywords import is_ai_related

PLATFORM = "linux_do"
BASE = "https://linux.do"
LATEST = f"{BASE}/latest.json"

_EXTRA_NOISE = {"linux.do", "meta.discourse.org"}
_ASSET_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".pdf")


def parse_discourse_json(html: str) -> dict:
    """Pure: extract the JSON object from a browser-rendered .json page.
    Returns {} if the page isn't JSON (e.g. a Cloudflare challenge)."""
    text = BeautifulSoup(html or "", "html.parser").get_text()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return {}


def ai_topic_ids(latest_json: dict) -> list[tuple[int, str]]:
    """Pure: (id, title) of AI-related topics from a latest.json payload."""
    topics = latest_json.get("topic_list", {}).get("topics", [])
    return [(t["id"], t.get("title", "")) for t in topics
            if t.get("id") and is_ai_related(t.get("title", ""))]


def extract_topic_links(topic_json: dict, title: str) -> list[Candidate]:
    """Pure: external AI-service links from a topic's posts (cooked HTML)."""
    posts = topic_json.get("post_stream", {}).get("posts", [])
    out, seen = [], set()
    for p in posts:
        soup = BeautifulSoup(p.get("cooked", ""), "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href.startswith("http") or href.lower().endswith(_ASSET_EXT):
                continue
            dom = domain_of(href)
            if not dom or dom in seen or is_noise_domain(dom):
                continue
            if any(dom == d or dom.endswith("." + d) for d in _EXTRA_NOISE):
                continue
            seen.add(dom)
            out.append(Candidate(url=href, name=title[:80] or dom,
                                 description=title[:160],
                                 source_platform=PLATFORM))
    return out


async def fetch_candidates(max_topics: int = 12) -> list[Candidate]:
    from ..browser import render
    from ._base import dedup_by_domain
    # Cloudflare may challenge the first render; retry a couple of times.
    latest = {}
    for _ in range(3):
        latest = parse_discourse_json(await render(LATEST))
        if latest.get("topic_list"):
            break
    topics = ai_topic_ids(latest)[:max_topics]
    pages = await asyncio.gather(
        *[render(f"{BASE}/t/{tid}.json") for tid, _ in topics])
    out: list[Candidate] = []
    for (tid, title), html in zip(topics, pages):
        if html:
            out.extend(extract_topic_links(parse_discourse_json(html), title))
    return dedup_by_domain(out)


async def collect(db: DB, max_topics: int = 12) -> int:
    from . import store_candidates
    return store_candidates(db, PLATFORM, await fetch_candidates(max_topics))


if __name__ == "__main__":
    async def _main():
        cands = await fetch_candidates()
        print(f"Found {len(cands)} linux.do AI-service candidates:")
        for c in cands[:30]:
            print(f"  {c.domain:<30} {c.name[:40]}")
    asyncio.run(_main())
