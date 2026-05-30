"""Tests for Apify collector item->Candidate mapping (pure, no network)."""
import asyncio

from ai_finder.collectors.apify_sources import (
    PLATFORM_PH,
    fetch_candidates,
    item_to_candidate,
)


def test_maps_producthunt_item():
    item = {"name": "GeekAI", "website": "https://geekai.co",
            "tagline": "An LLM gateway API", "votesCount": 120}
    c = item_to_candidate(item, PLATFORM_PH)
    assert c is not None
    assert c.domain == "geekai.co"
    assert c.name == "GeekAI"
    assert c.upvotes == 120
    assert c.source_platform == PLATFORM_PH


def test_maps_alternate_field_names():
    item = {"title": "VisionAI", "url": "https://visionai.dev",
            "summary": "neural image tagging", "points": "42"}
    c = item_to_candidate(item, PLATFORM_PH)
    assert c.domain == "visionai.dev"
    assert c.name == "VisionAI"
    assert c.upvotes == 42


def test_skips_non_ai_item():
    item = {"name": "BudgetBuddy", "website": "https://budget.app",
            "tagline": "track your spending"}
    assert item_to_candidate(item, PLATFORM_PH) is None


def test_skips_item_without_url():
    item = {"name": "AI thing", "tagline": "great AI tool"}
    assert item_to_candidate(item, PLATFORM_PH) is None


def test_fetch_without_token_returns_empty():
    # No token passed and APIFY_TOKEN unset in test env -> empty, no crash.
    out = asyncio.run(fetch_candidates(token=None, actors={}))
    assert out == []
