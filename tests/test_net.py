"""Tests for net.py: noise filter, backoff, rate limiter, retry."""

import time

import httpx
import pytest

from ai_finder import net
from ai_finder.db import DB, Candidate, is_noise_domain


def test_is_noise_domain():
    assert is_noise_domain("github.com")
    assert is_noise_domain("gist.github.com")
    assert is_noise_domain("")
    assert not is_noise_domain("geekai.co")


def test_is_noise_domain_news():
    assert is_noise_domain("bbc.com")
    assert is_noise_domain("techcrunch.com")
    assert is_noise_domain("steamcommunity.com")
    assert is_noise_domain("futurism.com")
    assert is_noise_domain("theatlantic.com")
    assert is_noise_domain("lemmy.world")
    assert is_noise_domain("feddit.it")
    assert not is_noise_domain("notta.ai")


def test_is_noise_domain_nonpublic():
    assert is_noise_domain("127.0.0.1")
    assert is_noise_domain("localhost")
    assert is_noise_domain("multi-user.target")
    assert is_noise_domain("myhost")  # no TLD
    assert is_noise_domain("nas.local")
    assert not is_noise_domain("real-tool.ai")


def test_backoff_monotonic_cap():
    # full-jitter: bounded by base*2^attempt, and by cap
    for a in range(6):
        d = net.backoff_delay(a, base=0.5, cap=10.0)
        assert 0 <= d <= min(10.0, 0.5 * (2**a))


def test_random_ua_in_pool():
    assert net.random_ua() in net.USER_AGENTS


def test_db_rejects_noise_domain(tmp_path):
    db = DB(tmp_path / "t.db")
    sid, new = db.upsert_candidate(
        Candidate(url="https://github.com/foo/bar", source_platform="hn")
    )
    assert sid == -1 and new is False
    assert db.stats()["total"] == 0
    db.close()


@pytest.mark.asyncio
async def test_rate_limiter_enforces_delay():
    rl = net.RateLimiter(per_domain_delay=0.2)
    t0 = time.monotonic()
    await rl.wait("https://x.ai/a")
    await rl.wait("https://x.ai/b")  # same host -> must wait ~0.2s
    assert time.monotonic() - t0 >= 0.2


@pytest.mark.asyncio
async def test_fetch_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(net, "backoff_delay", lambda *a, **k: 0.0)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        r = await net.fetch(client, "https://retry.test", max_retries=3)
    assert r is not None and r.text == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_fetch_all_aligns_and_handles_failures(monkeypatch):
    monkeypatch.setattr(net, "backoff_delay", lambda *a, **k: 0.0)

    def handler(request):
        if "bad" in str(request.url):
            return httpx.Response(500)
        return httpx.Response(200, text=f"ok:{request.url.host}")

    transport = httpx.MockTransport(handler)
    OrigClient = httpx.AsyncClient

    class FakeClient(OrigClient):
        def __init__(self, *a, **k):
            k.pop("transport", None)
            super().__init__(transport=transport, **k)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    urls = ["https://a.ai", "https://bad.ai", "https://c.ai"]
    res = await net.fetch_all(urls, per_domain_delay=0, max_retries=0)
    assert len(res) == 3
    assert res[0].text == "ok:a.ai"
    assert res[1] is None  # failed -> None, aligned
    assert res[2].text == "ok:c.ai"


@pytest.mark.asyncio
async def test_fetch_text_stealth_fallback(monkeypatch):
    def handler(request):
        return httpx.Response(403)  # blocked

    transport = httpx.MockTransport(handler)

    async def fake_stealth(url, *a, **k):
        return "<html>recovered</html>"

    monkeypatch.setattr("ai_finder.browser.render_stealth", fake_stealth)
    monkeypatch.setattr(net, "backoff_delay", lambda *a, **k: 0.0)

    async with httpx.AsyncClient(transport=transport) as client:
        # no stealth -> empty
        plain = await net.fetch_text(client, "https://x.ai", max_retries=0)
        assert plain == ""
        # stealth -> recovered
        recovered = await net.fetch_text(client, "https://x.ai", max_retries=0, stealth=True)
        assert recovered == "<html>recovered</html>"


@pytest.mark.asyncio
async def test_fetch_gives_up_returns_none(monkeypatch):
    monkeypatch.setattr(net, "backoff_delay", lambda *a, **k: 0.0)

    def handler(request):
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        r = await net.fetch(client, "https://down.test", max_retries=1)
    assert r is None
