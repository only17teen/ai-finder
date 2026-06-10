"""Tests for Linux forums link extraction (pure, no network)."""

from ai_finder.collectors.linux_forums import extract_candidates

FORUM = "https://lwn.net/"

HTML = """
<html><body>
  <div class="post">
    Check out this great AI image tool:
    <a href="https://coolgenai.io/start">CoolGenAI</a>
  </div>
  <div class="post">
    <a href="https://example-recipes.com">My recipe blog</a> nothing techy here
  </div>
  <div class="post">
    <a href="https://llmrouter.dev">LLMRouter</a> - a neural inference proxy
  </div>
  <div class="nav">
    <a href="https://lwn.net/Articles/123">internal link</a>
    <a href="https://twitter.com/share">share on twitter about AI</a>
  </div>
</body></html>
"""


def test_extracts_ai_external_links():
    cands = extract_candidates(HTML, FORUM)
    domains = {c.domain for c in cands}
    assert "coolgenai.io" in domains  # anchor context mentions AI
    assert "llmrouter.dev" in domains  # parent text mentions neural


def test_skips_non_ai_links():
    cands = extract_candidates(HTML, FORUM)
    assert "example-recipes.com" not in {c.domain for c in cands}


def test_skips_internal_and_noise():
    cands = extract_candidates(HTML, FORUM)
    domains = {c.domain for c in cands}
    assert "lwn.net" not in domains  # forum-internal
    assert "twitter.com" not in domains  # social noise even if AI-mentioned


def test_dedup_within_page():
    html = '<a href="https://dup.ai/a">AI one</a><a href="https://dup.ai/b">AI two</a>'
    cands = extract_candidates(html, FORUM)
    assert [c.domain for c in cands].count("dup.ai") == 1
