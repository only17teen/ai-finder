"""Tests for mastodon collector card mapping (pure)."""
from ai_finder.collectors.mastodon import card_to_candidate


def test_card_ai_external_kept():
    card = {"url": "https://geekai.co", "title": "GeekAI LLM gateway",
            "description": "one API for every model"}
    c = card_to_candidate(card)
    assert c is not None
    assert c.domain == "geekai.co"
    assert c.name == "GeekAI LLM gateway"


def test_card_skips_non_ai():
    assert card_to_candidate(
        {"url": "https://recipes.example", "title": "my cooking blog"}) is None


def test_card_skips_mastodon_and_shorteners():
    assert card_to_candidate(
        {"url": "https://mastodon.uno/x", "title": "AI news"}) is None
    assert card_to_candidate(
        {"url": "https://bit.ly/abc", "title": "great AI tool"}) is None


def test_card_none_or_no_url():
    assert card_to_candidate(None) is None
    assert card_to_candidate({"title": "AI thing"}) is None
