"""Networking robustness: UA rotation, per-domain rate limit, retry/backoff.

Polite by default. Used by HTTP-based collectors. Pure helpers (`backoff_delay`,
`is_noise_domain`) are unit-tested; the async fetch is integration-level.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import OrderedDict

import httpx

from .db import NOISE_DOMAINS, domain_of, is_noise_domain  # noqa: F401

log = logging.getLogger("ai_finder")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

RETRY_STATUS = {429, 500, 502, 503, 504}


class StealthHeaders:
    """Provides headers synchronized with User-Agents to bypass fingerprinting."""

    _COMMON_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    _COMMON_LANG = "en-US,en;q=0.9"

    @classmethod
    def get(cls) -> dict[str, str]:
        ua = random.choice(USER_AGENTS)
        headers = {
            "User-Agent": ua,
            "Accept": cls._COMMON_ACCEPT,
            "Accept-Language": cls._COMMON_LANG,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
        # Crude Sec-CH-UA inference
        if "Chrome" in ua:
            ver = ua.split("Chrome/")[1].split(".")[0]
            headers["Sec-CH-UA"] = (
                f'"Not-A.Brand";v="99", "Chromium";v="{ver}", "Google Chrome";v="{ver}"'
            )
            headers["Sec-CH-UA-Mobile"] = "?0"
            headers["Sec-CH-UA-Platform"] = '"Windows"' if "Windows" in ua else '"Linux"'
        return headers


def random_ua() -> str:
    return random.choice(USER_AGENTS)


def backoff_delay(attempt: int, base: float = 0.5, cap: float = 30.0) -> float:
    """Exponential backoff with full jitter (pure)."""
    return random.uniform(0, min(cap, base * (2**attempt)))


class _BoundedDict(OrderedDict):
    def __init__(self, maxsize=4096):
        super().__init__()
        self._maxsize = maxsize

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if len(self) > self._maxsize:
            self.popitem(last=False)  # evict oldest


class RateLimiter:
    """Enforce a minimum delay between requests to the same host with latency adaptation."""

    def __init__(self, per_domain_delay: float = 1.0):
        self.delay = per_domain_delay
        self._last = _BoundedDict()
        self._locks = _BoundedDict()
        self._latencies = _BoundedDict()  # track recent response times

    def report_latency(self, url: str, latency: float):
        """Report server response time to adapt delay."""
        dom = domain_of(url)
        # EMA of latency
        prev = self._latencies.get(dom, latency)
        self._latencies[dom] = 0.7 * prev + 0.3 * latency

    def _get_adapted_delay(self, dom: str) -> float:
        # If latency is > 2s, increase base delay
        latency = self._latencies.get(dom, 0.0)
        if latency > 2.0:
            return self.delay * (latency / 1.0)  # scale delay by latency
        return self.delay

    async def wait(self, url: str) -> None:
        if self.delay <= 0:
            return
        dom = domain_of(url)
        if dom not in self._locks:
            self._locks[dom] = asyncio.Lock()
        lock = self._locks[dom]
        async with lock:
            now = time.monotonic()
            elapsed = now - self._last.get(dom, 0.0)
            adapted = self._get_adapted_delay(dom)
            if elapsed < adapted:
                await asyncio.sleep(adapted - elapsed)
            self._last[dom] = time.monotonic()


async def fetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    limiter: RateLimiter | None = None,
    max_retries: int = 3,
    timeout: float = 20.0,
) -> httpx.Response | None:
    """GET with UA rotation, rate limiting and retry/backoff on 429/5xx.

    Returns the Response, or None if all attempts failed.
    """
    for attempt in range(max_retries + 1):
        if limiter:
            await limiter.wait(url)
        try:
            start = time.monotonic()
            r = await client.get(url, timeout=timeout, headers=StealthHeaders.get())
            latency = time.monotonic() - start
            if limiter:
                limiter.report_latency(url, latency)

            if r.status_code in RETRY_STATUS and attempt < max_retries:
                d = backoff_delay(attempt)
                log.warning("fetch %s -> %s, retry in %.1fs", url, r.status_code, d)
                await asyncio.sleep(d)
                continue
            r.raise_for_status()
            return r
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            if attempt >= max_retries:
                log.error("fetch %s failed after %d attempts: %s", url, attempt + 1, e)
                return None
            await asyncio.sleep(backoff_delay(attempt))
    return None


async def fetch_text(
    client, url, *, limiter=None, max_retries: int = 3, stealth: bool = False
) -> str:
    """Fetch one URL's text. With `stealth`, fall back to Camoufox when the
    plain httpx fetch is blocked/empty. Returns '' on total failure."""
    r = await fetch(client, url, limiter=limiter, max_retries=max_retries)
    if r and r.text:
        return r.text
    if stealth:
        from .browser import render_stealth

        return await render_stealth(url)
    return ""


async def fetch_all(
    urls, per_domain_delay: float = 1.0, max_retries: int = 3, user_agent: str | None = None
):
    """Fetch many URLs concurrently in one client. Returns responses aligned
    to `urls` (None where the fetch failed). Shared by HTTP collectors."""
    headers = {"User-Agent": user_agent or random_ua()}
    limiter = RateLimiter(per_domain_delay=per_domain_delay)
    sem = asyncio.Semaphore(50)

    async def _bounded(client, u):
        async with sem:
            return await fetch(client, u, limiter=limiter, max_retries=max_retries)

    async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
        return await asyncio.gather(*[_bounded(client, u) for u in urls])


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
