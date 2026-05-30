"""Shared building blocks for collectors.

`html_collect` captures the dominant pattern — fetch a list of URLs, run a pure
``extractor(html, url) -> list[Candidate]`` over each, and dedup by domain — so
adding a server-rendered source is just a SOURCES list + an extractor.
"""
from __future__ import annotations

from collections.abc import Callable

from ..models import Candidate


def dedup_by_domain(cands, prefer_higher_upvotes: bool = False) -> list[Candidate]:
    """Collapse candidates sharing a domain. First wins, unless
    `prefer_higher_upvotes` keeps the higher-upvote variant."""
    uniq: dict[str, Candidate] = {}
    for c in cands:
        if not c.domain:
            continue
        cur = uniq.get(c.domain)
        if cur is None or (prefer_higher_upvotes and c.upvotes > cur.upvotes):
            uniq[c.domain] = c
    return list(uniq.values())


async def html_collect(
    sources: list[str],
    extractor: Callable[[str, str], list[Candidate]],
    *,
    prefer_higher_upvotes: bool = False,
) -> list[Candidate]:
    """Fetch each URL in `sources` concurrently, apply `extractor`, dedup."""
    from ..net import fetch_all
    out: list[Candidate] = []
    responses = await fetch_all(sources)
    for url, r in zip(sources, responses):
        if r:
            out.extend(extractor(r.text, url))
    return dedup_by_domain(out, prefer_higher_upvotes)
