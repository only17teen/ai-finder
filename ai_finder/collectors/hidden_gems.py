"""Hidden-gems collector: Chinese + European niche AI directories.

Targets sources the CIS/EN crowd rarely touches: Chinese aggregators (ai-bot.cn)
that list domestic .cn tools, European directories, and HuggingFace trending
Spaces (often niche CN/EU research demos). All server-rendered or JSON — no
browser needed. Link/JSON parsing is pure and unit-tested.
"""
from __future__ import annotations

import asyncio

import httpx
from bs4 import BeautifulSoup

from ..db import DB, Candidate, domain_of, is_noise_domain

PLATFORM = "hidden_gems"

# Server-rendered directories (no JS). Each links out to tool domains.
HTML_SOURCES = [
    "https://ai-bot.cn/",            # 中国 — domestic Chinese tools (.cn)
    "https://www.aigc.cn/",          # 中国 — large AIGC directory (265+ tools)
    "https://www.aixploria.com/en/",  # EU (France) — large niche listing
    "https://intelligence-artificielle.com/",  # EU (France) — FR-native dir
    "https://aitools.fyi/",          # EU — indie tools
]

# rankmyai region rankings -> per-tool detail pages -> outbound site.
# Surfaces region-tagged Asian gems (KR: Samsung SDS, 42dot, Rebellions; etc.)
RANKMYAI_REGIONS = [
    "https://www.rankmyai.com/rankings/top-ai-tools-china",
    "https://www.rankmyai.com/rankings/top-ai-tools-south-korea",
    "https://www.rankmyai.com/rankings/top-ai-tools-japan",
    "https://www.rankmyai.com/rankings/top-ai-tools-taiwan",
    "https://www.rankmyai.com/rankings/top-ai-tools-singapore",
]

HF_SPACES_API = ("https://huggingface.co/api/spaces"
                 "?sort=likes&direction=-1&limit=80&full=true")

# Extra directory/affiliate hosts to ignore beyond the global noise set.
_EXTRA_NOISE = {
    "ai-bot.cn", "aigc.cn", "aixploria.com", "aitools.fyi", "huggingface.co",
    "hf.co", "beian.miit.gov.cn", "miitbeian.gov.cn", "weibo.com",
    "qq.com", "bilibili.com", "zhihu.com", "getrewardful.com",
    "beian.gov.cn", "gov.cn", "prf.hn", "go.sjv.io", "sjv.io",
    "rankmyai.com", "creativecommons.org", "wordpress.org",
}


def _skip(domain: str, src_domain: str) -> bool:
    if not domain or domain == src_domain or is_noise_domain(domain):
        return True
    return any(domain == d or domain.endswith("." + d) for d in _EXTRA_NOISE)


def extract_from_directory(html: str, source_url: str) -> list[Candidate]:
    """Pure: external tool links from a server-rendered directory page."""
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
        seen.add(dom)
        name = a.get_text(" ", strip=True) or dom
        out.append(Candidate(url=href, name=name[:80],
                             description=name[:160], source_platform=PLATFORM))
    return out


def extract_rankmyai_links(html: str) -> list[str]:
    """Pure: per-tool detail-page URLs from a rankmyai ranking page."""
    soup = BeautifulSoup(html, "html.parser")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "/tools/" not in href:
            continue
        if not href.startswith("http"):
            href = "https://www.rankmyai.com" + href
        if "rankmyai.com/tools/" not in href:
            continue
        if href not in seen:
            seen.add(href)
            out.append(href)
    return out


def extract_rankmyai_outbound(html: str) -> Candidate | None:
    """Pure: outbound tool site from a rankmyai detail page."""
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(strip=True) if soup.title else "")
    prefer, fallback = None, None
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith("http") or _skip(domain_of(href), "rankmyai.com"):
            continue
        if "visit" in a.get_text(" ", strip=True).lower():
            prefer = href
            break
        fallback = fallback or href
    url = prefer or fallback
    if not url:
        return None
    return Candidate(url=url, name=(title or domain_of(url))[:80],
                     description=title[:160], source_platform=PLATFORM)


def hf_space_to_candidate(space: dict) -> Candidate | None:
    """Pure: map a HuggingFace Space record to a Candidate.

    Uses the public Space URL; niche research demos often expose an API.
    """
    sid = space.get("id")
    if not sid:
        return None
    card = space.get("cardData") or {}
    title = card.get("title") or sid.split("/")[-1]
    desc = card.get("short_description") or ""
    return Candidate(
        url=f"https://huggingface.co/spaces/{sid}",
        name=str(title)[:80],
        description=str(desc)[:160],
        source_platform=PLATFORM,
        upvotes=int(space.get("likes") or 0),
    )


async def fetch_candidates() -> list[Candidate]:
    from ..net import RateLimiter, fetch
    limiter = RateLimiter(per_domain_delay=1.0)
    out: list[Candidate] = []
    async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
        for url in HTML_SOURCES:
            r = await fetch(client, url, limiter=limiter)
            if r:
                out.extend(extract_from_directory(r.text, url))
        # rankmyai region rankings -> detail pages -> outbound sites.
        for region_url in RANKMYAI_REGIONS:
            r = await fetch(client, region_url, limiter=limiter)
            if not r:
                continue
            details = extract_rankmyai_links(r.text)[:15]
            pages = await asyncio.gather(
                *[fetch(client, d, limiter=limiter) for d in details])
            for pr in pages:
                if pr:
                    c = extract_rankmyai_outbound(pr.text)
                    if c and c.domain:
                        out.append(c)
        # HuggingFace trending Spaces (JSON).
        r = await fetch(client, HF_SPACES_API, limiter=limiter)
        if r:
            try:
                for sp in r.json():
                    c = hf_space_to_candidate(sp)
                    if c:
                        out.append(c)
            except Exception:
                pass
    uniq: dict[str, Candidate] = {}
    for c in out:
        if c.domain:
            # keep the higher-upvote variant on domain collision
            cur = uniq.get(c.domain)
            if not cur or c.upvotes > cur.upvotes:
                uniq[c.domain] = c
    return list(uniq.values())


async def collect(db: DB) -> int:
    cands = await fetch_candidates()
    new = sum(db.upsert_candidate(c)[1] for c in cands)
    db.log_source(PLATFORM, len(cands), new)
    return new


if __name__ == "__main__":
    async def _main():
        cands = await fetch_candidates()
        print(f"Found {len(cands)} hidden-gem candidates (CN/EU/HF):")
        for c in cands[:30]:
            print(f"  [{c.upvotes:>4}] {c.domain:<30} {c.name[:40]}")
    asyncio.run(_main())
