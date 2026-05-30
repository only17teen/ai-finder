"""Tests for foss_sources collector (pure functions, no network)."""
from ai_finder.collectors.foss_sources import (
    algolia_hit_to_candidate,
    extract_links,
)

SRC = "https://lobste.rs/t/ai"

HTML = """
<html><body>
  <li><a href="https://localllm.dev">LocalLLM</a> a self-hosted LLM runner</li>
  <li><a href="https://recipes.example">Recipe app</a> nothing here</li>
  <li><a href="https://neuralforge.io">NeuralForge</a> AI inference toolkit</li>
  <li><a href="https://lobste.rs/s/abc">internal comments</a> AI discussion</li>
  <li><a href="https://github.com/x/y">repo</a> cool AI project</li>
</body></html>
"""


def test_extract_ai_external_links():
    cands = extract_links(HTML, SRC)
    domains = {c.domain for c in cands}
    assert "localllm.dev" in domains
    assert "neuralforge.io" in domains


def test_extract_skips_noninternal_noise_and_nonai():
    cands = extract_links(HTML, SRC)
    domains = {c.domain for c in cands}
    assert "recipes.example" not in domains   # not AI
    assert "lobste.rs" not in domains          # internal
    assert "github.com" not in domains         # global noise


def test_algolia_hit_kept():
    hit = {"url": "https://geekai.co", "title": "Show HN: GeekAI LLM API",
           "points": 88}
    c = algolia_hit_to_candidate(hit)
    assert c is not None
    assert c.domain == "geekai.co"
    assert c.upvotes == 88


def test_algolia_hit_skips_non_ai_and_noise():
    assert algolia_hit_to_candidate(
        {"url": "https://x.com/a", "title": "AI tool", "points": 5}) is None
    assert algolia_hit_to_candidate(
        {"url": "https://shop.com", "title": "buy shoes"}) is None
    assert algolia_hit_to_candidate({"title": "no url AI"}) is None
