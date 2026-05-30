"""Tests for launch collector (pure extraction)."""
from ai_finder.collectors.launch import extract_candidates

SRC = "https://microlaunch.net/"

HTML = """
<html><body>
  <div class="card"><a href="https://snapai.io">SnapAI</a>
    <p>AI image upscaler</p></div>
  <div class="card"><a href="https://budgetzen.com">BudgetZen</a>
    <p>simple budgeting</p></div>
  <div class="card"><a href="https://promptforge.dev">PromptForge</a>
    <p>LLM prompt manager</p></div>
  <a href="https://microlaunch.net/about">About (AI launches)</a>
  <a href="https://twitter.com/ml">Follow AI news</a>
</body></html>
"""


def test_extracts_ai_launches():
    cands = extract_candidates(HTML, SRC)
    domains = {c.domain for c in cands}
    assert "snapai.io" in domains
    assert "promptforge.dev" in domains


def test_skips_nonai_self_social():
    cands = extract_candidates(HTML, SRC)
    domains = {c.domain for c in cands}
    assert "budgetzen.com" not in domains
    assert "microlaunch.net" not in domains
    assert "twitter.com" not in domains
