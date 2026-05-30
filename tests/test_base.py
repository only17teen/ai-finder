"""Tests for shared collector base helpers."""
import asyncio

from ai_finder.collectors._base import dedup_by_domain, html_collect
from ai_finder.models import Candidate


def test_dedup_by_domain_first_wins():
    cands = [Candidate(url="https://a.ai/1", name="first", source_platform="x"),
             Candidate(url="https://a.ai/2", name="second", source_platform="x"),
             Candidate(url="https://b.ai", source_platform="x")]
    out = dedup_by_domain(cands)
    assert {c.domain for c in out} == {"a.ai", "b.ai"}
    assert next(c for c in out if c.domain == "a.ai").name == "first"


def test_dedup_prefer_higher_upvotes():
    cands = [Candidate(url="https://a.ai/1", upvotes=5, source_platform="x"),
             Candidate(url="https://a.ai/2", upvotes=50, source_platform="x")]
    out = dedup_by_domain(cands, prefer_higher_upvotes=True)
    assert len(out) == 1 and out[0].upvotes == 50


def test_html_collect(monkeypatch):
    def extractor(html, url):
        return [Candidate(url=html.strip(), source_platform="x")]

    async def fake_fetch_all(urls, **k):
        class R:
            def __init__(self, t): self.text = t
        return [R("https://one.ai"), None, R("https://two.ai")]
    monkeypatch.setattr("ai_finder.net.fetch_all", fake_fetch_all)

    out = asyncio.run(html_collect(["u1", "u2", "u3"], extractor))
    assert {c.domain for c in out} == {"one.ai", "two.ai"}  # None skipped
