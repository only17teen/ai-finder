"""Site verifier: detect API docs, referral program, pricing, and metadata.

`analyze_html` is a pure function. `verify` renders a live site with Playwright
and runs the analysis. Results update the DB.
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .browser import render
from .db import DB

# Path/keyword signals for each capability.
API_PATHS = (
    "/api",
    "/docs",
    "/documentation",
    "/developer",
    "/developers",
    "/reference",
    "/swagger",
    "/openapi",
    "/api-docs",
    "/open",
    "/kaifa",
    "/wendang",
)
API_TEXT = (
    "api",
    "api key",
    "api reference",
    "developer",
    "rest api",
    "graphql",
    "sdk",
    "documentation",
)

REFERRAL_PATHS = (
    "/affiliate",
    "/affiliates",
    "/referral",
    "/refer",
    "/partner",
    "/partners",
    "/fenxiao",
    "/tuiguang",
)
REFERRAL_TEXT = (
    "affiliate",
    "referral",
    "refer a friend",
    "earn commission",
    "invite friends",
    "earn",
    "commission",
    "partner program",
)

PRICING_PATHS = ("/pricing", "/plans", "/price", "/billing", "/jiage", "/huiyuan", "/huiyuandingjia")
PRICING_TEXT = (
    "pricing",
    "free tier",
    "pay as you go",
    "/month",
    "per month",
    "subscription",
    "free trial",
)

# Strong phrases for body-text fallback.
API_STRONG = ("api key", "api reference", "rest api", "graphql", "api文档")
REFERRAL_STRONG = (
    "affiliate program",
    "referral program",
    "refer a friend",
    "earn commission",
    "invite friends",
)
PRICING_STRONG = ("free tier", "pay as you go", "per month", "free trial", "会员定价", "价格", "定价", "套餐", "vip")

_COMMISSION_RE = re.compile(
    r"(\d{1,3})\s*%\s*(?:recurring\s*)?(?:commission|cut|payout|revenue|rev[\s-]?share)"
    r"|earn\s+(?:up\s+to\s+)?(\d{1,3})\s*%"
    # Chinese: number% then chinese word (40%分成) — allow zero or more spaces
    r"|(\d{1,3})\s*%\s*(?:返佣|佣金|分成|提成|返现)"
    # Chinese: chinese word then number% (返佣30%, 返佣 30%, 佣金高达 50%, 佣金高达50%)
    r"|(?:返佣|佣金|分成|提成|返现)(?:\s*(?:高达|最高|最多))?\s*(\d{1,3})\s*%",
    re.I,
)

_AFFILIATE_SIGNATURES = {
    "rewardful": "Rewardful",
    "getrewardful": "Rewardful",
    "firstpromoter": "FirstPromoter",
    "fprom.co": "FirstPromoter",
    "partnerstack": "PartnerStack",
    "growsumo": "PartnerStack",
    "tolt.io": "Tolt",
    "gettolt": "Tolt",
    "lemonsqueezy": "LemonSqueezy",
    "tapfiliate": "Tapfiliate",
    "impact.com": "Impact",
    "promotekit": "PromoteKit",
    "affonso": "Affonso",
    "reditus": "Reditus",
}

_TECH_SIGNATURES = {
    "vercel-ai": ("x-vercel-ai", "vercel-ai-sdk", "ai/react", "ai/core"),
    "langchain": ("langchain", "langsmith", "lc_js"),
    "openai-compatible": ("/v1/chat/completions", "/v1/completions", "openai-organization"),
    "dify": ("dify", "dify-client"),
    "coze": ("coze", "coze-client"),
    "flowise": ("flowise", "flowise-client"),
    "gradio": ("gradio_config", "gradio-app"),
    "streamlit": ("st-key", "streamlit-app"),
}

_CATEGORIES = {
    "image-gen": (
        "image generation",
        "text to image",
        "stable diffusion",
        "midjourney",
        "upscaler",
        "dall-e",
        "flux",
    ),
    "text-gen": (
        "chatbot",
        "llm",
        "writing assistant",
        "copywriting",
        "essay writer",
        "gpt-4",
        "claude",
        "llama",
    ),
    "video-gen": (
        "video generation",
        "text to video",
        "sora",
        "runway",
        "pika",
        "avatar",
        "heygen",
    ),
    "audio-gen": (
        "text to speech",
        "voice cloning",
        "music generation",
        "elevenlabs",
        "suno",
        "udio",
    ),
    "productivity": (
        "automation",
        "workflow",
        "summarization",
        "transcription",
        "meeting assistant",
        "zapier",
    ),
    "coding": ("code assistant", "copilot", "autocomplete", "code generation", "programming"),
}


def detect_affiliate_platform(html: str) -> str:
    text = (html or "").lower()
    for sig, name in _AFFILIATE_SIGNATURES.items():
        if sig in text:
            return name
    return ""


def detect_tech_stack(html: str, headers: dict = None) -> list[str]:
    stacks = []
    text = (html or "").lower()
    headers_str = str({k.lower(): v.lower() for k, v in (headers or {}).items()})
    for name, sigs in _TECH_SIGNATURES.items():
        if any(sig in text for sig in sigs) or any(sig in headers_str for sig in sigs):
            stacks.append(name)
    if "/v1/chat/completions" in text or "openai-compatible" in text:
        if "openai-compatible" not in stacks:
            stacks.append("openai-compatible")
    return sorted(list(set(stacks)))


def detect_category(text: str) -> str:
    text = text.lower()
    best_cat, max_matches = "", 0
    for cat, keywords in _CATEGORIES.items():
        matches = sum(1 for kw in keywords if kw in text)
        if matches > max_matches:
            max_matches, best_cat = matches, cat
    return best_cat


def _links(soup: BeautifulSoup, base_url: str):
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "javascript:", "#")):
            continue
        text = a.get_text(" ", strip=True).lower()
        yield urljoin(base_url, href), text, href.lower()


def _match(links, page_text, paths, texts, strong_texts=None):
    for url, anchor, href in links:
        path = urlparse(url).path.lower().rstrip("/")
        if any(path == p or path.startswith(p + "/") for p in paths) or any(
            t == anchor or t in anchor for t in texts
        ):
            return url
    strong = strong_texts if strong_texts is not None else texts
    return "__text__" if any(t in page_text for t in strong) else ""


def extract_commission(text: str) -> str:
    """Extract a commission percentage from promotional text.

    Handles English patterns ("50% commission", "earn 25%") and Chinese
    patterns both directions: "40%分成" and "返佣30%" / "佣金高达 50%".
    Returns the first match as "N%", or "" if nothing matches.
    """
    m = _COMMISSION_RE.search(text or "")
    if not m:
        return ""
    pct = next((g for g in m.groups() if g), None)
    return f"{pct}%" if pct else ""


def analyze_html(html: str, base_url: str, headers: dict = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    links = list(_links(soup, base_url))
    body_text = soup.get_text(" ", strip=True).lower()

    api_url = _match(links, body_text, API_PATHS, API_TEXT, API_STRONG)
    ref_url = _match(links, body_text, REFERRAL_PATHS, REFERRAL_TEXT, REFERRAL_STRONG)
    price_url = _match(links, body_text, PRICING_PATHS, PRICING_TEXT, PRICING_STRONG)

    tech_stack = detect_tech_stack(html, headers)
    if not api_url and "openai-compatible" in tech_stack:
        api_url = "__inferred__"

    title = soup.title.get_text(strip=True) if soup.title else ""
    desc_el = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    description = desc_el.get("content", "").strip() if desc_el else ""
    og = soup.find("meta", attrs={"property": "og:image"})

    def clean(u: str) -> str:
        return "" if u in ("", "__text__", "__inferred__") else u

    combined_meta = f"{title} {description}".lower()
    return {
        "has_api": bool(api_url),
        "api_docs_url": clean(api_url),
        "has_referral": bool(ref_url),
        "referral_url": clean(ref_url),
        "referral_commission": extract_commission(body_text),
        "affiliate_platform": detect_affiliate_platform(html),
        "pricing_info": "found" if price_url else "",
        "pricing_model": clean(price_url),
        "name": title[:120],
        "description": description[:300],
        "og_image": og.get("content", "") if og else "",
        "tech_stack": ",".join(tech_stack),
        "category": detect_category(combined_meta),
    }


async def verify(url: str) -> dict:
    base = url if "://" in url else f"https://{url}"
    html = await render(base)
    if not html:
        from .browser import render_stealth

        html = await render_stealth(base)
    if not html:
        return {}
    findings = analyze_html(html, base)
    return await _probe_missing(base, findings)


_PROBE_PATHS = {
    "api": [
        "/docs",
        "/api",
        "/api-docs",
        "/developers",
        "/developer",
        "/reference",
        "/open",
        "/openapi",
        "/api/v1/chat/completions",
        "/.well-known/ai-plugin.json",
        "/v1/models",
    ],
    "referral": [
        "/affiliate",
        "/affiliates",
        "/referral",
        "/partners",
        "/partner",
        "/fenxiao",
        "/tuiguang",
    ],
    "pricing": ["/pricing", "/plans", "/price"],
}


def merge_findings(base: dict, probed: dict) -> dict:
    out = dict(base)
    if not out.get("has_api") and probed.get("has_api"):
        out["has_api"] = True
        out["api_docs_url"] = probed.get("api_docs_url") or probed.get("__url__", "")
    if not out.get("has_referral") and probed.get("has_referral"):
        out["has_referral"] = True
        out["referral_url"] = probed.get("referral_url") or probed.get("__url__", "")
        if not out.get("referral_commission"):
            out["referral_commission"] = probed.get("referral_commission", "")
    if not out.get("affiliate_platform") and probed.get("affiliate_platform"):
        out["affiliate_platform"] = probed["affiliate_platform"]
    if not out.get("pricing_info") and probed.get("pricing_info"):
        out["pricing_info"] = "found"
        out["pricing_model"] = probed.get("pricing_model") or probed.get("__url__", "")

    existing_stacks = set(filter(None, out.get("tech_stack", "").split(",")))
    new_stacks = set(filter(None, probed.get("tech_stack", "").split(",")))
    out["tech_stack"] = ",".join(sorted(list(existing_stacks | new_stacks)))

    if not out.get("category") and probed.get("category"):
        out["category"] = probed["category"]
    return out


async def _probe_missing(base_url: str, findings: dict) -> dict:
    from urllib.parse import urljoin

    import httpx

    from .net import StealthHeaders

    needed = [
        cap
        for cap, key in (
            ("api", "has_api"),
            ("referral", "has_referral"),
            ("pricing", "pricing_info"),
        )
        if not findings.get(key)
    ]

    async with httpx.AsyncClient(follow_redirects=True, headers=StealthHeaders.get()) as client:
        fails = 0
        for cap in needed:
            for path in _PROBE_PATHS[cap]:
                if fails >= 3:
                    return findings
                if findings.get(
                    {"api": "has_api", "referral": "has_referral", "pricing": "pricing_info"}[cap]
                ):
                    break
                target = urljoin(base_url, path)
                try:
                    r = await client.get(target, timeout=8)
                except (httpx.HTTPError, httpx.TimeoutException, OSError):
                    fails += 1
                    continue
                fails = 0
                if r.status_code != 200 or not r.text:
                    continue
                probed = analyze_html(r.text, target, headers=dict(r.headers))
                probed["__url__"] = target
                findings = merge_findings(findings, probed)
    return findings


def _persist_fields(row, findings: dict) -> dict:
    import time

    fields = {"last_checked": time.time()}
    if findings:
        fields.update(
            {
                "has_api": int(findings["has_api"]),
                "api_docs_url": findings["api_docs_url"],
                "has_referral": int(findings["has_referral"]),
                "referral_url": findings["referral_url"],
                "referral_commission": findings["referral_commission"],
                "affiliate_platform": findings.get("affiliate_platform", ""),
                "pricing_info": findings["pricing_info"],
                "pricing_model": findings["pricing_model"],
                "tech_stack": findings.get("tech_stack", ""),
                "category": findings.get("category", ""),
                "verified_at": time.time(),
                "status": "verified",
            }
        )
        if findings["name"] and not row["name"]:
            fields["name"] = findings["name"]
        if findings["description"]:
            fields["description"] = findings["description"]
    else:
        fields["status"] = "unreachable"
    return fields


def _row_url(row) -> str:
    raw = row["source_url"] or row["domain"]
    return raw if "://" in raw else f"https://{raw}"


async def verify_service(db: DB, service_id: int) -> dict:
    row = db.get(service_id)
    if not row:
        return {}
    findings = await verify(row["source_url"] or row["domain"])
    db.update_service(service_id, **_persist_fields(row, findings))
    return findings


async def verify_services_batch(db: DB, service_ids: list[int], concurrency: int = 6) -> int:
    from .browser import render_many, render_stealth_many

    rows = [db.get(sid) for sid in service_ids if db.get(sid)]
    urls = {r["id"]: _row_url(r) for r in rows}
    html_by_url = await render_many(list(urls.values()), concurrency=concurrency)
    blocked = [u for u in urls.values() if not html_by_url.get(u)]
    if blocked:
        html_by_url.update(await render_stealth_many(blocked))
    for r in rows:
        url = urls[r["id"]]
        html = html_by_url.get(url, "")
        findings = analyze_html(html, url) if html else {}
        if findings:
            findings = await _probe_missing(url, findings)
        db.update_service(r["id"], **_persist_fields(r, findings))
    return len(rows)


if __name__ == "__main__":
    import sys

    target = sys.argv[sys.argv.index("--url") + 1] if "--url" in sys.argv else "geekai.co"

    async def _main():
        print(f"Verifying {target} ...")
        f = await verify(target)
        if not f:
            print("  unreachable / no HTML")
            return
        for k, v in f.items():
            print(f"  {k:12}: {v}")

    asyncio.run(_main())
