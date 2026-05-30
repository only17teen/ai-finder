"""Tests for site verifier analysis (pure, no browser)."""
import asyncio

from ai_finder.verifier import analyze_html, extract_commission, verify_service
from ai_finder.db import DB, Candidate

BASE = "https://geekai.co"

FULL = """
<html><head>
  <title>GeekAI - LLM Gateway</title>
  <meta name="description" content="One API for every LLM.">
  <meta property="og:image" content="https://geekai.co/og.png">
</head><body>
  <nav>
    <a href="/api-docs">API Documentation</a>
    <a href="/pricing">Pricing</a>
    <a href="/affiliate">Affiliate Program</a>
  </nav>
  <p>Join our affiliate program and earn 30% recurring commission.</p>
</body></html>
"""

BARE = """
<html><head><title>Recipe Box</title></head>
<body><p>Just a simple recipe site. Nothing to see.</p></body></html>
"""


def test_detects_all_capabilities():
    r = analyze_html(FULL, BASE)
    assert r["has_api"] and r["api_docs_url"] == "https://geekai.co/api-docs"
    assert r["has_referral"] and r["referral_url"] == "https://geekai.co/affiliate"
    assert r["pricing_model"] == "https://geekai.co/pricing"
    assert r["referral_commission"] == "30%"
    assert r["name"] == "GeekAI - LLM Gateway"
    assert r["description"] == "One API for every LLM."
    assert r["og_image"] == "https://geekai.co/og.png"


def test_bare_site_has_nothing():
    r = analyze_html(BARE, BASE)
    assert not r["has_api"]
    assert not r["has_referral"]
    assert r["referral_commission"] == ""


def test_commission_patterns():
    assert extract_commission("earn up to 50% commission") == "50%"
    assert extract_commission("20% recurring commission") == "20%"
    assert extract_commission("get 25% rev-share") == "25%"
    assert extract_commission("no money here") == ""


def test_chinese_commission_patterns():
    assert extract_commission("邀请好友，返佣30%") == "30%"
    assert extract_commission("佣金高达 50%") == "50%"
    assert extract_commission("40%分成") == "40%"


CN_FULL = """
<html><head>
  <title>秘塔AI - 智能搜索</title>
  <meta name="description" content="最好用的AI搜索工具">
</head><body>
  <nav>
    <a href="/open">开放平台</a>
    <a href="/huiyuan">会员定价</a>
    <a href="/fenxiao">分销推广</a>
  </nav>
  <p>加入我们的推广计划，返佣30%。</p>
</body></html>
"""


def test_detects_chinese_capabilities():
    r = analyze_html(CN_FULL, "https://metaso.cn")
    assert r["has_api"] and r["api_docs_url"] == "https://metaso.cn/open"
    assert r["has_referral"] and r["referral_url"] == "https://metaso.cn/fenxiao"
    assert r["pricing_model"] == "https://metaso.cn/huiyuan"
    assert r["referral_commission"] == "30%"
    assert r["name"] == "秘塔AI - 智能搜索"


def test_text_only_signal_does_not_set_url():
    html = "<html><body><p>We have a great API for developers</p></body></html>"
    r = analyze_html(html, BASE)
    assert r["has_api"] is True
    assert r["api_docs_url"] == ""  # signal from text, no specific link


def test_verify_service_persists(tmp_path, monkeypatch):
    db = DB(tmp_path / "t.db")
    sid, _ = db.upsert_candidate(
        Candidate(url="https://geekai.co", source_platform="hn"))

    async def fake_render(url, *a, **k):
        return FULL
    monkeypatch.setattr("ai_finder.verifier.render", fake_render)

    findings = asyncio.run(verify_service(db, sid))
    assert findings["has_api"]
    row = db.get(sid)
    assert row["has_api"] == 1 and row["has_referral"] == 1
    assert row["status"] == "verified"
    assert row["referral_commission"] == "30%"
    db.close()


def test_verify_service_unreachable(tmp_path, monkeypatch):
    db = DB(tmp_path / "t.db")
    sid, _ = db.upsert_candidate(
        Candidate(url="https://dead.example", source_platform="hn"))

    async def fake_render(url, *a, **k):
        return ""
    monkeypatch.setattr("ai_finder.verifier.render", fake_render)

    asyncio.run(verify_service(db, sid))
    assert db.get(sid)["status"] == "unreachable"
    db.close()


def test_verify_services_batch(tmp_path, monkeypatch):
    from ai_finder.verifier import verify_services_batch
    db = DB(tmp_path / "t.db")
    good, _ = db.upsert_candidate(
        Candidate(url="https://geekai.co", source_platform="hn"))
    dead, _ = db.upsert_candidate(
        Candidate(url="https://dead.example", source_platform="hn"))

    async def fake_render_many(urls, *a, **k):
        return {u: (FULL if "geekai" in u else "") for u in urls}
    monkeypatch.setattr("ai_finder.browser.render_many", fake_render_many)

    n = asyncio.run(verify_services_batch(db, [good, dead]))
    assert n == 2
    assert db.get(good)["status"] == "verified"
    assert db.get(good)["has_api"] == 1
    assert db.get(dead)["status"] == "unreachable"
    db.close()


def test_merge_findings_fills_missing():
    from ai_finder.verifier import merge_findings
    base = {"has_api": False, "api_docs_url": "", "has_referral": True,
            "referral_url": "https://x.ai/aff", "referral_commission": "20%",
            "pricing_info": "", "pricing_model": ""}
    probed = {"has_api": True, "api_docs_url": "https://x.ai/docs",
              "has_referral": False, "pricing_info": "found",
              "pricing_model": "", "__url__": "https://x.ai/docs"}
    out = merge_findings(base, probed)
    assert out["has_api"] and out["api_docs_url"] == "https://x.ai/docs"
    assert out["referral_url"] == "https://x.ai/aff"   # preserved
    assert out["pricing_info"] == "found"
    assert out["pricing_model"] == "https://x.ai/docs"  # from __url__


def test_merge_findings_no_overwrite_when_present():
    from ai_finder.verifier import merge_findings
    base = {"has_api": True, "api_docs_url": "https://x.ai/api",
            "has_referral": True, "referral_url": "https://x.ai/aff",
            "referral_commission": "30%", "pricing_info": "found",
            "pricing_model": "https://x.ai/pricing"}
    out = merge_findings(base, {"has_api": True,
                                "api_docs_url": "https://other/docs",
                                "__url__": "https://other/docs"})
    assert out["api_docs_url"] == "https://x.ai/api"   # unchanged
