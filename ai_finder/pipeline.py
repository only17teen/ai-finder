"""Collection + verification orchestration.

Separates the *what runs and in what order* (pipeline) from the *CLI surface*
(main.py). Holds the source registry, concurrent collection with per-source
error isolation, and the verification pass.
"""
from __future__ import annotations

import asyncio
import logging

from . import verifier
from .collectors import (
    ai_directories,
    apify_sources,
    asian_dev,
    forums,
    foss_sources,
    github_trending,
    hackernews,
    hidden_gems,
    intl_forums,
    launch,
    linux_do,
    linux_forums,
    mastodon,
    reddit_rss,
    telegram_channels,
)
from .db import DB

log = logging.getLogger("ai_finder")

# Canonical collector names (also the valid values for `run --source`).
SOURCE_NAMES = [
    "hackernews", "linux_forums", "apify", "ai_directories", "github_trending",
    "hidden_gems", "foss", "forums", "asian_dev", "launch", "reddit", "telegram",
    "intl_forums", "mastodon", "linux_do",
]


def source_registry(db: DB, cfg: dict) -> dict:
    """Map source name -> zero-arg coroutine factory for enabled sources."""
    return {
        "hackernews": lambda: hackernews.collect(
            db, cfg.get("limits", {}).get("hackernews", 100)),
        "linux_forums": lambda: linux_forums.collect(db),
        "apify": lambda: apify_sources.collect(
            db, cfg.get("apify", {}).get("token", "")),
        "ai_directories": lambda: ai_directories.collect(db),
        "github_trending": lambda: github_trending.collect(
            db, cfg.get("limits", {}).get("github_trending", 25)),
        "hidden_gems": lambda: hidden_gems.collect(db),
        "foss": lambda: foss_sources.collect(db),
        "forums": lambda: forums.collect(db),
        "asian_dev": lambda: asian_dev.collect(db),
        "launch": lambda: launch.collect(db),
        "reddit": lambda: reddit_rss.collect(db),
        "intl_forums": lambda: intl_forums.collect(db),
        "mastodon": lambda: mastodon.collect(db),
        "linux_do": lambda: linux_do.collect(db),
        "telegram": lambda: telegram_channels.collect(
            db, 
            cfg.get("telegram", {}).get("api_id"), 
            cfg.get("telegram", {}).get("api_hash"), 
            cfg.get("telegram", {}).get("channels", [])
        ),
    }


async def collect(db: DB, cfg: dict, only: str | None) -> int:
    """Run enabled collectors concurrently. Logs per-source failures."""
    src = cfg.get("sources", {})
    registry = source_registry(db, cfg)
    names = [n for n in registry if src.get(n) and only in (None, n)]
    
    if not names:
        log.warning("No enabled sources matched (only=%r). Check your config.toml.", only)
        return 0
        
    results = await asyncio.gather(
        *[registry[n]() for n in names], return_exceptions=True)
    total = 0
    for name, res in zip(names, results):
        if isinstance(res, Exception):
            log.error("collector %s failed: %s", name, res)
        else:
            total += res or 0
            log.info("collector %s: %d new", name, res or 0)
    return total


async def verify_pending(db: DB, concurrency: int = 6,
                         retry_cooldown_h: float = 24.0,
                         max_verify: int = 100) -> int:
    """Verify pending services + retry unreachable ones past the cooldown.

    Transient failures (timeouts, blips) shouldn't strand a service forever, so
    `unreachable` entries older than `retry_cooldown_h` hours get another shot.
    Caps each run at `max_verify` sites (leftovers stay pending for next run) so
    a big collection batch can't make a single run take unbounded time.
    """
    seen_ids: set[int] = set()
    due = []
    
    for r in db.by_status("pending"):
        if r["id"] not in seen_ids:
            seen_ids.add(r["id"])
            due.append(r)
            
    if retry_cooldown_h > 0:
        for r in db.stale_unreachable(retry_cooldown_h * 3600):
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                due.append(r)
                
    if not due:
        return 0
        
    ids = [r["id"] for r in due[:max_verify]]
    return await verifier.verify_services_batch(db, ids, concurrency=concurrency)
