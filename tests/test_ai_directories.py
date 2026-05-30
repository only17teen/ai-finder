"""Tests for AI directory link extraction (pure, no browser)."""
from ai_finder.collectors.ai_directories import (
    extract_candidates,
    extract_detail_links,
    extract_outbound,
)

SRC = "https://theresanaiforthat.com/"

HTML = """
<html><body>
  <div class="tool">
    <a href="https://geekai.co">GeekAI</a>
    <p>LLM gateway with a developer API</p>
  </div>
  <div class="tool">
    <a href="https://paintly.app">Paintly</a>
    <p>AI image generation studio</p>
  </div>
  <div class="tool">
    <a href="https://taxhelper.com">TaxHelper</a>
    <p>file your taxes faster</p>
  </div>
  <a href="https://theresanaiforthat.com/about">About us (AI directory)</a>
  <a href="https://twitter.com/taaft">Follow our AI news</a>
</body></html>
"""


def test_extracts_ai_tools():
    cands = extract_candidates(HTML, SRC)
    domains = {c.domain for c in cands}
    assert "geekai.co" in domains
    assert "paintly.app" in domains


def test_flags_api_hint_in_description():
    cands = extract_candidates(HTML, SRC)
    geek = next(c for c in cands if c.domain == "geekai.co")
    assert geek.description.startswith("[api hint]")
    paintly = next(c for c in cands if c.domain == "paintly.app")
    assert not paintly.description.startswith("[api hint]")


def test_skips_non_ai_and_self_and_social():
    cands = extract_candidates(HTML, SRC)
    domains = {c.domain for c in cands}
    assert "taxhelper.com" not in domains
    assert "theresanaiforthat.com" not in domains
    assert "twitter.com" not in domains


LISTING = """
<html><body>
  <a href="/ai/geekai">GeekAI</a>
  <a href="/ai/paintly">Paintly</a>
  <a href="/about">About</a>
  <a href="https://external.com/x">external</a>
  <a href="/ai/geekai">GeekAI dup</a>
</body></html>
"""

DETAIL = """
<html><head><title>GeekAI - LLM Gateway</title></head><body>
  <a href="https://theresanaiforthat.com/ai/geekai">back</a>
  <a href="https://twitter.com/geekai">twitter</a>
  <a href="https://geekai.co" class="btn">Visit Website</a>
</body></html>
"""


def test_extract_detail_links():
    links = extract_detail_links(LISTING, SRC)
    assert links == [
        "https://theresanaiforthat.com/ai/geekai",
        "https://theresanaiforthat.com/ai/paintly",
    ]  # /about skipped, external skipped, dup removed


def test_extract_outbound_prefers_visit_link():
    c = extract_outbound(DETAIL, "https://theresanaiforthat.com/ai/geekai")
    assert c is not None
    assert c.domain == "geekai.co"  # not the directory or twitter
    assert c.name == "GeekAI - LLM Gateway"


def test_extract_outbound_none_when_no_external():
    html = '<html><body><a href="https://twitter.com/x">x</a></body></html>'
    assert extract_outbound(html, SRC) is None
