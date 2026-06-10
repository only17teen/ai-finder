"""Tests for HackerNews collector + keyword filtering."""

from ai_finder.collectors.hackernews import story_to_candidate
from ai_finder.keywords import is_ai_related, mentions_api


def test_is_ai_related():
    assert is_ai_related("Show HN: An LLM-powered code reviewer")
    assert is_ai_related("My new GPT wrapper")
    assert is_ai_related("Neural search engine")
    assert not is_ai_related("Show HN: A budgeting app for families")
    # 'ai' must not match inside 'email' / 'maintain'
    assert not is_ai_related("A tool to maintain your email list")


def test_mentions_api():
    assert mentions_api("We expose a REST API for developers")
    assert not mentions_api("Just a simple landing page")


def test_story_to_candidate_keeps_ai_external():
    item = {
        "type": "story",
        "title": "Show HN: GeekAI - LLM gateway",
        "url": "https://geekai.co",
        "score": 42,
    }
    c = story_to_candidate(item)
    assert c is not None
    assert c.domain == "geekai.co"
    assert c.name == "GeekAI - LLM gateway"
    assert c.upvotes == 42
    assert c.source_platform == "hackernews"


def test_story_to_candidate_skips_non_ai():
    item = {
        "type": "story",
        "title": "Show HN: Recipe app",
        "url": "https://recipes.example",
        "score": 10,
    }
    assert story_to_candidate(item) is None


def test_story_to_candidate_skips_textpost():
    item = {"type": "story", "title": "Ask HN: best AI tools?", "score": 5}
    assert story_to_candidate(item) is None


def test_story_to_candidate_skips_jobs():
    item = {"type": "job", "title": "AI startup hiring", "url": "https://x.co"}
    assert story_to_candidate(item) is None
