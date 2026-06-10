"""Tests for intl_forums (Korean GeekNews) extraction (pure)."""

from ai_finder.collectors.intl_forums import extract_candidates

SRC = "https://news.hada.io/"

HTML = """
<html><body>
  <div class="topic"><a href="https://orchidfiles.com">대화형 AI 도구</a>
    <p>AI conversation tool</p></div>
  <div class="topic"><a href="https://recipes.kr">요리 블로그</a>
    <p>cooking blog</p></div>
  <div class="topic"><a href="https://llmgw.io">LLM Gateway</a>
    <p>neural inference proxy</p></div>
  <a href="https://news.hada.io/topic/123">internal AI thread</a>
  <a href="https://twitter.com/x">AI news on twitter</a>
</body></html>
"""


def test_extracts_korean_ai_links():
    cands = extract_candidates(HTML, SRC)
    domains = {c.domain for c in cands}
    assert "orchidfiles.com" in domains
    assert "llmgw.io" in domains


def test_skips_nonai_internal_social():
    cands = extract_candidates(HTML, SRC)
    domains = {c.domain for c in cands}
    assert "recipes.kr" not in domains
    assert "news.hada.io" not in domains
    assert "twitter.com" not in domains
