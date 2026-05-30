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
# Feeds richest in shared AI services: latest + resource (资源荟萃) +
# welfare (福利羊毛, deals/invites) + domestic (国产替代, CN alternatives).
FEEDS = [
    f"{BASE}/c/resource/14.json",
    f"{BASE}/c/welfare/36.json",
    f"{BASE}/c/domestic/98.json",
    f"{BASE}/latest.json",
]

# linux.do itself + Chinese netdisks/shorteners are not the AI service.
_EXTRA_NOISE = {
    "linux.do", "meta.discourse.org",
    "pan.baidu.com", "pan.quark.cn", "aliyundrive.com", "alipan.com",
    "cloud.189.cn", "lanzou.com", "123pan.com", "weiyun.com",
    "t.me", "telegra.ph", "docs.qq.com",
}
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


_BARE_DOMAIN_RE = re.compile(
    r"(?<![@\w.])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:ai|io|app|dev|co|com|net|cn|org|me|sh|gg|so|xyz|tech|tools))"
    r"(?![\w.])", re.I)


def _ok_domain(dom: str, seen: set) -> bool:
    if not dom or dom in seen or is_noise_domain(dom):
        return False
    return not any(dom == d or dom.endswith("." + d) for d in _EXTRA_NOISE)


def extract_topic_links(topic_json: dict, title: str) -> list[Candidate]:
    """Pure: external AI-service links from a topic's posts.

    Picks up both <a> hrefs and bare-text domains (services are often shared
    as plain text on linux.do), filtering noise/netdisks/assets.
    """
    posts = topic_json.get("post_stream", {}).get("posts", [])
    out, seen = [], set()
    for p in posts:
        cooked = p.get("cooked", "")
        soup = BeautifulSoup(cooked, "html.parser")
        # 1) anchored links
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href.startswith("http") or href.lower().endswith(_ASSET_EXT):
                continue
            dom = domain_of(href)
            if not _ok_domain(dom, seen):
                continue
            seen.add(dom)
            out.append(Candidate(url=href, name=title[:80] or dom,
                                 description=title[:160], source_platform=PLATFORM))
        # 2) bare-text domains (e.g. "推荐 chyqd.com")
        for m in _BARE_DOMAIN_RE.finditer(soup.get_text(" ")):
            dom = domain_of(m.group(1))
            if not _ok_domain(dom, seen):
                continue
            seen.add(dom)
            out.append(Candidate(url=f"https://{dom}", name=title[:80] or dom,
                                 description=title[:160], source_platform=PLATFORM))
    return out


async def _render_json(render, url: str, attempts: int = 3) -> dict:
    """Render a Discourse .json URL, retrying past Cloudflare challenges."""
    for _ in range(attempts):
        data = parse_discourse_json(await render(url))
        if data:
            return data
    return {}


async def fetch_candidates(max_topics: int = 15) -> list[Candidate]:
    from ..browser import render_stealth as render
    from ._base import dedup_by_domain
    # Gather AI topic ids across feeds (dedup by id, keep first title).
    seen_ids: dict[int, str] = {}
    for feed in FEEDS:
        data = await _render_json(render, feed)
        for tid, title in ai_topic_ids(data):
            seen_ids.setdefault(tid, title)
    out: list[Candidate] = []
    # Sequential: camoufox is heavy; concurrent instances are unreliable.
    for tid, title in list(seen_ids.items())[:max_topics]:
        tj = await _render_json(render, f"{BASE}/t/{tid}.json")
        if tj:
            out.extend(extract_topic_links(tj, title))
    return dedup_by_domain(out)


async def collect(db: DB, max_topics: int = 15) -> int:
    from . import store_candidates
    return store_candidates(db, PLATFORM, await fetch_candidates(max_topics))


if __name__ == "__main__":
    async def _main():
        cands = await fetch_candidates()
        print(f"Found {len(cands)} linux.do AI-service candidates:")
        for c in cands[:30]:
            print(f"  {c.domain:<30} {c.name[:40]}")
    asyncio.run(_main())
