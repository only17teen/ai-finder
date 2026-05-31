"""Tests for browser stealth batch helper (no real browser launch)."""
import asyncio
import sys

from ai_finder import browser


def test_render_stealth_many_empty():
    assert asyncio.run(browser.render_stealth_many([])) == {}


def test_render_stealth_many_without_camoufox(monkeypatch):
    # Simulate camoufox not installed -> every URL maps to '' (no crash).
    monkeypatch.setitem(sys.modules, "camoufox.async_api", None)
    out = asyncio.run(browser.render_stealth_many(["https://a.ai", "https://b.ai"]))
    assert out == {"https://a.ai": "", "https://b.ai": ""}
