"""Telegram public-channel collector (Telethon).

Reads recent messages from public AI channels and extracts AI-related links.
Requires Telegram API credentials (api_id, api_hash). Only public channels.
Link extraction from message text is pure and unit-tested.
"""
from __future__ import annotations

import asyncio
import re

from ..db import Candidate, domain_of, DB
from ..keywords import is_ai_related

PLATFORM = "telegram"
_URL_RE = re.compile(r"https?://[^\s\)\]\>\"']+")

_NOISE = {
    "t.me", "telegram.me", "telegram.org", "youtube.com", "youtu.be",
    "twitter.com", "x.com", "instagram.com", "facebook.com", "google.com",
}


def extract_links(text: str) -> list[Candidate]:
    """Pure: pull AI-related external links from a message's text."""
    if not text:
        return []
    out: list[Candidate] = []
    seen: set[str] = set()
    # Only keep links when the surrounding message is AI-related.
    ai_ctx = is_ai_related(text)
    for m in _URL_RE.finditer(text):
        url = m.group(0).rstrip(".,;")
        dom = domain_of(url)
        if not dom or dom in seen:
            continue
        if any(dom == n or dom.endswith("." + n) for n in _NOISE):
            continue
        if not (ai_ctx or is_ai_related(url)):
            continue
        seen.add(dom)
        out.append(Candidate(url=url, name=dom, description=text[:160],
                             source_platform=PLATFORM))
    return out


async def fetch_candidates(
    api_id: int | None = None,
    api_hash: str | None = None,
    channels: list[str] | None = None,
    per_channel: int = 50,
    session: str = "ai_finder",
) -> list[Candidate]:
    if not (api_id and api_hash and channels):
        return []
    from telethon import TelegramClient
    out: list[Candidate] = []
    client = TelegramClient(session, api_id, api_hash)
    await client.start()
    try:
        for ch in channels:
            try:
                async for msg in client.iter_messages(ch, limit=per_channel):
                    out.extend(extract_links(msg.message or ""))
            except Exception:
                continue
    finally:
        await client.disconnect()
    uniq: dict[str, Candidate] = {}
    for c in out:
        uniq.setdefault(c.domain, c)
    return list(uniq.values())


async def collect(db: DB, api_id=None, api_hash=None,
                  channels=None) -> int:
    cands = await fetch_candidates(api_id, api_hash, channels)
    new = sum(db.upsert_candidate(c)[1] for c in cands)
    db.log_source(PLATFORM, len(cands), new)
    return new


if __name__ == "__main__":
    sample = ("New AI tool drop! Check https://geekai.co for an LLM API, "
              "and https://example.com/about . Join https://t.me/aichan")
    print("Link-extraction demo (no credentials needed):")
    for c in extract_links(sample):
        print(f"  {c.domain:<20} {c.url}")
    print("\nSet api_id/api_hash + channels in config to run live.")
