"""Tests for reddit_rss collector (pure RSS extraction)."""
from ai_finder.collectors.reddit_rss import extract_from_rss

RSS = """
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>New self-hosted LLM router released</title>
    <content type="html">&lt;a href="https://llmrouter.dev"&gt;site&lt;/a&gt;
      &lt;a href="https://preview.redd.it/x.png"&gt;img&lt;/a&gt;
      &lt;a href="https://reddit.com/r/x"&gt;sub&lt;/a&gt;</content>
  </entry>
  <entry>
    <title>My vacation photos</title>
    <content type="html">&lt;a href="https://photos.example"&gt;pics&lt;/a&gt;</content>
  </entry>
  <entry>
    <title>AI image upscaler tool</title>
    <content type="html">&lt;a href="https://upscale.ai/start"&gt;try&lt;/a&gt;
      &lt;a href="https://cdn.x/pic.jpg"&gt;asset&lt;/a&gt;</content>
  </entry>
</feed>
"""


def test_extracts_ai_external_links():
    cands = extract_from_rss(RSS)
    domains = {c.domain for c in cands}
    assert "llmrouter.dev" in domains
    assert "upscale.ai" in domains


def test_skips_nonai_reddit_internal_and_assets():
    cands = extract_from_rss(RSS)
    domains = {c.domain for c in cands}
    assert "photos.example" not in domains      # non-AI post
    assert "reddit.com" not in domains           # internal
    assert "preview.redd.it" not in domains      # reddit media
    assert not any(d.endswith("/pic.jpg") for d in domains)  # asset filtered


def test_empty_feed():
    assert extract_from_rss("<feed></feed>") == []
