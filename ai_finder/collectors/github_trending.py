"""GitHub Trending collector (httpx + BeautifulSoup).

Trending AI repos often have a hosted/SaaS version with an API. We parse the
trending page for AI repos, then read each repo page for its homepage link
(the real product site). Repos with an external homepage are the leads.
Both parsers are pure and unit-tested.
"""

from __future__ import annotations

import asyncio

import httpx
from bs4 import BeautifulSoup

from ..db import DB, Candidate, domain_of
from ..keywords import is_ai_related

PLATFORM = "github_trending"
TRENDING_URL = "https://github.com/trending?since=weekly"


def parse_trending(html: str) -> list[dict]:
    """Pure: extract AI repos from a trending page.

    Returns dicts: {repo, repo_url, description, stars}.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for art in soup.select("article.Box-row"):
        a = art.select_one("h2 a")
        if not a:
            continue
        repo = a.get_text(" ", strip=True).replace(" ", "").replace("/", "/")
        href = a.get("href", "")
        repo_url = "https://github.com" + href if href.startswith("/") else href
        desc_el = art.select_one("p")
        desc = desc_el.get_text(" ", strip=True) if desc_el else ""
        if not (is_ai_related(repo) or is_ai_related(desc)):
            continue
        rows.append({"repo": repo, "repo_url": repo_url, "description": desc})
    return rows


def extract_homepage(repo_html: str) -> str:
    """Pure: find a repo's external homepage link, or '' if none/github."""
    soup = BeautifulSoup(repo_html, "html.parser")
    # GitHub marks the homepage link with itemprop="url" in the sidebar.
    el = soup.find("a", attrs={"itemprop": "url"}) or soup.select_one('a.text-bold[href^="http"]')
    href = el.get("href", "") if el else ""
    dom = domain_of(href)
    if not dom or dom == "github.com" or dom.endswith(".github.com"):
        return ""
    return href


async def fetch_candidates(limit: int = 25) -> list[Candidate]:
    from ..net import RateLimiter, fetch

    limiter = RateLimiter(per_domain_delay=1.0)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await fetch(client, TRENDING_URL, limiter=limiter)
        if not r:
            return []
        repos = parse_trending(r.text)[:limit]

        async def _one(repo: dict) -> Candidate | None:
            rr = await fetch(client, repo["repo_url"], limiter=limiter)
            home = extract_homepage(rr.text) if rr else ""
            url = home or repo["repo_url"]
            return Candidate(
                url=url,
                name=repo["repo"].split("/")[-1],
                description=repo["description"],
                source_platform=PLATFORM,
            )

        results = await asyncio.gather(*[_one(r) for r in repos])
    from ._base import dedup_by_domain

    return dedup_by_domain([c for c in results if c])


async def collect(db: DB, limit: int = 25) -> int:
    from . import store_candidates

    return store_candidates(db, PLATFORM, await fetch_candidates(limit))


if __name__ == "__main__":

    async def _main():
        cands = await fetch_candidates(25)
        print(f"Found {len(cands)} trending AI repos/sites:")
        for c in cands[:20]:
            print(f"  {c.domain:<30} {c.name[:45]}")

    asyncio.run(_main())
