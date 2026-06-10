"""Tests for forums collector (Lemmy + dev.to mapping, pure)."""

from ai_finder.collectors.forums import (
    devto_article_to_candidate,
    lemmy_post_to_candidate,
)


def test_lemmy_post_external_ai():
    pv = {
        "post": {"name": "Self-hosted LLM router", "url": "https://llmrouter.dev"},
        "counts": {"score": 42},
    }
    c = lemmy_post_to_candidate(pv)
    assert c is not None
    assert c.domain == "llmrouter.dev"
    assert c.upvotes == 42


def test_lemmy_post_skips_non_ai():
    pv = {
        "post": {"name": "My garden photos", "url": "https://garden.example"},
        "counts": {"score": 5},
    }
    assert lemmy_post_to_candidate(pv) is None


def test_lemmy_post_skips_noise_and_missing_url():
    assert (
        lemmy_post_to_candidate({"post": {"name": "AI tool", "url": "https://youtube.com/x"}})
        is None
    )
    assert lemmy_post_to_candidate({"post": {"name": "AI tool"}}) is None


def test_devto_article_external_ai():
    art = {
        "title": "Building an LLM API gateway",
        "canonical_url": "https://geekai.co/blog",
        "description": "how we built it",
        "positive_reactions_count": 30,
    }
    c = devto_article_to_candidate(art)
    assert c.domain == "geekai.co"
    assert c.upvotes == 30


def test_devto_skips_devto_hosted_and_nonai():
    assert (
        devto_article_to_candidate({"title": "AI thing", "canonical_url": "https://dev.to/x/post"})
        is None
    )
    assert (
        devto_article_to_candidate({"title": "my cat", "canonical_url": "https://blog.example"})
        is None
    )
