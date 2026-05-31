"""Shared Playwright helper: render a JS page to HTML."""
from __future__ import annotations

from contextlib import asynccontextmanager

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


@asynccontextmanager
async def browser_page():
    """Yield a Playwright page with a realistic UA + basic stealth."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
        # Basic anti-detection: hide the webdriver automation flag.
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        page = await ctx.new_page()
        try:
            yield page
        finally:
            await ctx.close()
            await browser.close()


async def render(url: str, wait: str = "domcontentloaded",
                 timeout: int = 30000) -> str:
    """Return rendered HTML for a URL, or '' on failure."""
    try:
        async with browser_page() as page:
            await page.goto(url, wait_until=wait, timeout=timeout)
            return await page.content()
    except Exception:
        return ""


async def render_many(urls: list[str], concurrency: int = 6,
                      wait: str = "domcontentloaded",
                      timeout: int = 30000) -> dict[str, str]:
    """Render many URLs reusing ONE browser. Returns {url: html} ('' on fail).

    Far faster than per-URL render(): single browser launch, N concurrent
    contexts bounded by `concurrency`.
    """
    if not urls:
        return {}
    from playwright.async_api import async_playwright
    results: dict[str, str] = {u: "" for u in urls}
    sem = __import__("asyncio").Semaphore(concurrency)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        async def _one(u: str):
            async with sem:
                ctx = await browser.new_context(
                    user_agent=UA, viewport={"width": 1366, "height": 768},
                    locale="en-US")
                await ctx.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',"
                    "{get:()=>undefined});")
                page = await ctx.new_page()
                try:
                    await page.goto(u, wait_until=wait, timeout=timeout)
                    results[u] = await page.content()
                except Exception:
                    results[u] = ""
                finally:
                    await ctx.close()

        import asyncio as _a
        await _a.gather(*[_one(u) for u in urls])
        await browser.close()
    return results


async def _stealth_page(browser, url: str, wait: str, timeout: int) -> str:
    page = await browser.new_page()
    try:
        await page.goto(url, wait_until=wait, timeout=timeout)
        await page.wait_for_timeout(2500)  # let Cloudflare's JS challenge resolve
        return await page.content()
    except Exception:
        return ""
    finally:
        await page.close()


async def render_stealth(url: str, wait: str = "domcontentloaded",
                         timeout: int = 35000) -> str:
    """Render a URL with Camoufox (anti-detect Firefox) to defeat Cloudflare
    and similar bot walls. Returns HTML, or '' on failure / if camoufox is
    unavailable. Heavier than render(); use only for protected sites."""
    try:
        from camoufox.async_api import AsyncCamoufox
    except ImportError:
        return ""
    try:
        async with AsyncCamoufox(headless=True, humanize=True) as browser:
            return await _stealth_page(browser, url, wait, timeout)
    except Exception:
        return ""


async def render_stealth_many(urls: list[str], wait: str = "domcontentloaded",
                              timeout: int = 35000) -> dict[str, str]:
    """Render many URLs reusing ONE Camoufox browser (sequential). Returns
    {url: html} ('' on fail). Avoids the per-URL browser-launch cost."""
    if not urls:
        return {}
    try:
        from camoufox.async_api import AsyncCamoufox
    except ImportError:
        return {u: "" for u in urls}
    results: dict[str, str] = {}
    try:
        async with AsyncCamoufox(headless=True, humanize=True) as browser:
            for u in urls:
                results[u] = await _stealth_page(browser, u, wait, timeout)
    except Exception:
        pass
    return {u: results.get(u, "") for u in urls}
