"""Networking robustness: UA rotation, per-domain rate limit, retry/backoff.

Polite by default. Used by HTTP-based collectors. Pure helpers (`backoff_delay`,
`is_noise_domain`) are unit-tested; the async fetch is integration-level.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time

import httpx

from .db import NOISE_DOMAINS, domain_of, is_noise_domain  # noqa: F401

log = logging.getLogger("ai_finder")

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Firefox/124.0",
]

RETRY_STATUS = {429, 500, 502, 503, 504}


def random_ua() -> str:
    return random.choice(USER_AGENTS)


def backoff_delay(attempt: int, base: float = 0.5, cap: float = 30.0) -> float:
    """Exponential backoff with full jitter (pure)."""
    return random.uniform(0, min(cap, base * (2 ** attempt)))


class RateLimiter:
    """Enforce a minimum delay between requests to the same host."""

    def __init__(self, per_domain_delay: float = 1.0):
        self.delay = per_domain_delay
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, url: str) -> None:
        if self.delay <= 0:
            return
        dom = domain_of(url)
        lock = self._locks.setdefault(dom, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            elapsed = now - self._last.get(dom, 0.0)
            if elapsed < self.delay:
                await asyncio.sleep(self.delay - elapsed)
            self._last[dom] = time.monotonic()


async def fetch(client: httpx.AsyncClient, url: str, *,
                limiter: RateLimiter | None = None,
                max_retries: int = 3, timeout: float = 20.0) -> httpx.Response | None:
    """GET with UA rotation, rate limiting and retry/backoff on 429/5xx.

    Returns the Response, or None if all attempts failed.
    """
    for attempt in range(max_retries + 1):
        if limiter:
            await limiter.wait(url)
        try:
            r = await client.get(url, timeout=timeout,
                                  headers={"User-Agent": random_ua()})
            if r.status_code in RETRY_STATUS and attempt < max_retries:
                d = backoff_delay(attempt)
                log.warning("fetch %s -> %s, retry in %.1fs", url, r.status_code, d)
                await asyncio.sleep(d)
                continue
            r.raise_for_status()
            return r
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            if attempt >= max_retries:
                log.error("fetch %s failed after %d attempts: %s",
                          url, attempt + 1, e)
                return None
            await asyncio.sleep(backoff_delay(attempt))
    return None


async def fetch_text(client, url, *, limiter=None, max_retries: int = 3,
                     stealth: bool = False) -> str:
    """Fetch one URL's text. With `stealth`, fall back to Camoufox when the
    plain httpx fetch is blocked/empty. Returns '' on total failure."""
    r = await fetch(client, url, limiter=limiter, max_retries=max_retries)
    if r and r.text:
        return r.text
    if stealth:
        from .browser import render_stealth
        return await render_stealth(url)
    return ""


async def fetch_all(urls, per_domain_delay: float = 1.0,
                    max_retries: int = 3, user_agent: str | None = None):
    """Fetch many URLs concurrently in one client. Returns responses aligned
    to `urls` (None where the fetch failed). Shared by HTTP collectors."""
    headers = {"User-Agent": user_agent or random_ua()}
    limiter = RateLimiter(per_domain_delay=per_domain_delay)
    async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
        return await asyncio.gather(
            *[fetch(client, u, limiter=limiter, max_retries=max_retries)
              for u in urls])


def setup_logging(verbose: bool = False, logfile: str = "ai_finder.log") -> None:
    """Configure structured logging to file + console."""
    handlers: list[logging.Handler] = [logging.FileHandler(logfile)]
    if verbose:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )
