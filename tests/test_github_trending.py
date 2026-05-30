"""Tests for GitHub trending parsing (pure, no network)."""
from ai_finder.collectors.github_trending import extract_homepage, parse_trending

TRENDING = """
<html><body>
  <article class="Box-row">
    <h2><a href="/acme/llm-router">acme / llm-router</a></h2>
    <p>A high-performance LLM inference gateway</p>
  </article>
  <article class="Box-row">
    <h2><a href="/bob/budget-cli">bob / budget-cli</a></h2>
    <p>Track your personal finances in the terminal</p>
  </article>
  <article class="Box-row">
    <h2><a href="/cat/neural-art">cat / neural-art</a></h2>
    <p>Generative diffusion art toolkit</p>
  </article>
</body></html>
"""


def test_parse_trending_keeps_ai_repos():
    rows = parse_trending(TRENDING)
    repos = {r["repo"] for r in rows}
    assert "acme/llm-router" in repos
    assert "cat/neural-art" in repos
    assert "bob/budget-cli" not in repos
    assert rows[0]["repo_url"] == "https://github.com/acme/llm-router"


def test_extract_homepage_external():
    html = '<a itemprop="url" href="https://llmrouter.io" class="text-bold">llmrouter.io</a>'
    assert extract_homepage(html) == "https://llmrouter.io"


def test_extract_homepage_none_when_only_github():
    html = '<a itemprop="url" href="https://github.com/acme/x">github</a>'
    assert extract_homepage(html) == ""


def test_extract_homepage_empty_when_missing():
    assert extract_homepage("<html><body>no link</body></html>") == ""
