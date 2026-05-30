"""Tests for Telegram message link extraction (pure, no network)."""
import asyncio

from ai_finder.collectors.telegram_channels import extract_links, fetch_candidates


def test_extracts_ai_links_from_message():
    text = "New LLM API tool: https://geekai.co and https://visionai.dev/docs"
    cands = extract_links(text)
    domains = {c.domain for c in cands}
    assert "geekai.co" in domains
    assert "visionai.dev" in domains


def test_skips_telegram_and_social_links():
    text = "Great AI news! https://t.me/somechannel https://twitter.com/x"
    assert extract_links(text) == []


def test_non_ai_message_yields_nothing():
    text = "Check out my cooking blog https://recipes.example"
    assert extract_links(text) == []


def test_ai_url_kept_even_if_text_neutral():
    text = "look here https://neural-art.io/start"
    cands = extract_links(text)
    assert {c.domain for c in cands} == {"neural-art.io"}


def test_dedup_and_punctuation_strip():
    text = "AI tools: https://x.ai, https://x.ai."
    cands = extract_links(text)
    assert [c.domain for c in cands] == ["x.ai"]


def test_fetch_without_credentials_returns_empty():
    out = asyncio.run(fetch_candidates(api_id=None, api_hash=None, channels=None))
    assert out == []
