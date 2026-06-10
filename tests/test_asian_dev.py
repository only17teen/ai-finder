"""Tests for asian_dev collector (pure text extraction)."""

from ai_finder.collectors.asian_dev import extract_from_text


def test_extracts_ai_links_from_body():
    body = "试试这个 https://metaso.cn 还有 https://aippt.cn/docs"
    cands = extract_from_text("秘塔AI搜索很好用", body, upvotes=10)
    domains = {c.domain for c in cands}
    assert "metaso.cn" in domains
    assert "aippt.cn" in domains
    assert all(c.upvotes == 10 for c in cands)


def test_non_ai_post_yields_nothing():
    body = "look https://recipes.example"
    assert extract_from_text("my cooking blog", body) == []


def test_skips_self_and_noise_and_dedup():
    body = "AI: https://v2ex.com/t/1 https://youtube.com/x https://tool.ai/a https://tool.ai/b"
    cands = extract_from_text("AI tools thread", body)
    domains = [c.domain for c in cands]
    assert "v2ex.com" not in domains
    assert "youtube.com" not in domains
    assert domains.count("tool.ai") == 1


def test_title_triggers_ai_context():
    # AI keyword in title, link in body without AI word -> still kept
    cands = extract_from_text("New LLM gateway", "https://gw.dev/start")
    assert {c.domain for c in cands} == {"gw.dev"}


def test_skips_image_assets_and_malformed():
    body = (
        "AI demo https://cdn.x/pic.png https://real-ai.dev "
        "https://<containerlab-host>/x https://s3.amazonaws.com/y.jpg"
    )
    cands = extract_from_text("AI tool", body)
    domains = {c.domain for c in cands}
    assert domains == {"real-ai.dev"}
