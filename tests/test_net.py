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
    assert not is_noise_domain("notta.ai")


def test_is_noise_domain_nonpublic():
    assert is_noise_domain("127.0.0.1")
    assert is_noise_domain("localhost")
    assert is_noise_domain("multi-user.target")
    assert is_noise_domain("myhost")            # no TLD
    assert is_noise_domain("nas.local")
    assert not is_noise_domain("real-tool.ai")


def test_backoff_monotonic_cap():
    # full-jitter: bounded by base*2^attempt, and by cap
    for a in range(6):
        d = net.backoff_delay(a, base=0.5, cap=10.0)
        assert 0 <= d <= min(10.0, 0.5 * (2 ** a))


def test_random_ua_in_pool():
    assert net.random_ua() in net.USER_AGENTS


def test_db_rejects_noise_domain(tmp_path):
    db = DB(tmp_path / "t.db")
    sid, new = db.upsert_candidate(
        Candidate(url="https://github.com/foo/bar", source_platform="hn"))
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
async def test_fetch_gives_up_returns_none(monkeypatch):
    monkeypatch.setattr(net, "backoff_delay", lambda *a, **k: 0.0)

    def handler(request):
        return httpx.Response(500)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        r = await net.fetch(client, "https://down.test", max_retries=1)
    assert r is None
