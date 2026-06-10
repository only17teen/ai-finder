"""Tests for hidden_gems collector (pure functions, no network)."""

from ai_finder.collectors.hidden_gems import (
    extract_from_directory,
    extract_rankmyai_links,
    extract_rankmyai_outbound,
    hf_space_to_candidate,
)

SRC = "https://ai-bot.cn/"

DIR_HTML = """
<html><body>
  <a href="https://ai-bot.cn/category">internal</a>
  <a href="https://metaso.cn">秘塔AI搜索</a>
  <a href="https://aippt.cn">AiPPT 一键生成PPT</a>
  <a href="https://github.com/x/y">repo</a>
  <a href="https://weibo.com/aibot">weibo</a>
  <a href="https://metaso.cn/dup">秘塔 dup</a>
</body></html>
"""


def test_extract_chinese_tools():
    cands = extract_from_directory(DIR_HTML, SRC)
    domains = {c.domain for c in cands}
    assert "metaso.cn" in domains
    assert "aippt.cn" in domains


def test_extract_skips_internal_noise_social_and_dups():
    cands = extract_from_directory(DIR_HTML, SRC)
    domains = [c.domain for c in cands]
    assert "ai-bot.cn" not in domains  # internal
    assert "github.com" not in domains  # global noise
    assert "weibo.com" not in domains  # CN social (extra noise)
    assert domains.count("metaso.cn") == 1  # dedup


def test_hf_space_to_candidate():
    sp = {
        "id": "qwen/Qwen-Image",
        "likes": 1234,
        "cardData": {"title": "Qwen Image", "short_description": "image generation"},
    }
    c = hf_space_to_candidate(sp)
    assert c.domain == "huggingface.co"
    assert c.name == "Qwen Image"
    assert c.upvotes == 1234
    assert "spaces/qwen/Qwen-Image" in c.url


def test_hf_space_without_card_uses_id():
    sp = {"id": "someorg/cool-demo", "likes": 0}
    c = hf_space_to_candidate(sp)
    assert c.name == "cool-demo"


def test_hf_space_no_id_returns_none():
    assert hf_space_to_candidate({}) is None


RANK_HTML = """
<html><body>
  <a href="/tools/uuid-1/samsung-sds">Samsung SDS</a>
  <a href="https://www.rankmyai.com/tools/uuid-2/42dot">42dot</a>
  <a href="/rankings/top-ai-tools-japan">Japan</a>
  <a href="/tools/uuid-1/samsung-sds">dup</a>
</body></html>
"""

RANK_DETAIL = """
<html><head><title>42dot - Autonomous AI</title></head><body>
  <a href="https://creativecommons.org/x">CC BY 4.0</a>
  <a href="https://42dot.ai" >Visit website</a>
</body></html>
"""


def test_extract_rankmyai_links():
    links = extract_rankmyai_links(RANK_HTML)
    assert links == [
        "https://www.rankmyai.com/tools/uuid-1/samsung-sds",
        "https://www.rankmyai.com/tools/uuid-2/42dot",
    ]  # ranking link skipped, dup removed, relative made absolute


def test_extract_rankmyai_outbound():
    c = extract_rankmyai_outbound(RANK_DETAIL)
    assert c is not None
    assert c.domain == "42dot.ai"  # not creativecommons / rankmyai
    assert c.name == "42dot - Autonomous AI"


def test_extract_rankmyai_outbound_none():
    html = '<html><body><a href="https://creativecommons.org/x">cc</a></body></html>'
    assert extract_rankmyai_outbound(html) is None
