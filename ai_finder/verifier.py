"""Site verifier: detect API docs, referral program, pricing, and metadata.

`analyze_html` is a pure function (unit-tested with fixtures). `verify` renders
a live site with Playwright and runs the analysis. Results update the DB.
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .browser import render
from .db import DB

# Path/keyword signals for each capability.
API_PATHS = ("/api", "/docs", "/documentation", "/developer", "/developers",
             "/reference", "swagger", "openapi", "/api-docs",
             "/open", "/openapi", "/kaifa", "/wendang")  # 开放平台/开发/文档
API_TEXT = ("api", "api key", "api reference", "developer", "rest api",
            "graphql", "sdk", "documentation",
            "开放平台", "开发者", "接口", "开发文档", "api文档", "调用")

REFERRAL_PATHS = ("/affiliate", "/affiliates", "/referral", "/refer",
                  "/partner", "/partners",
                  "/fenxiao", "/tuiguang", "/yaoqing", "/hehuoren")
REFERRAL_TEXT = ("affiliate", "referral", "refer a friend", "earn commission",
                 "invite friends", "earn", "commission", "partner program",
                 "分销", "推广", "邀请", "返佣", "佣金", "合伙人", "推荐奖励",
                 "联盟", "分成")

PRICING_PATHS = ("/pricing", "/plans", "/price", "/billing",
                 "/jiage", "/huiyuan", "/vip", "/chongzhi")
PRICING_TEXT = ("pricing", "free tier", "pay as you go", "/month", "per month",
                "subscription", "free trial",
                "价格", "定价", "会员", "套餐", "充值", "免费试用", "订阅",
                "元/月", "积分")

_COMMISSION_RE = re.compile(
    r"(\d{1,3})\s*%\s*(?:recurring\s*)?(?:commission|cut|payout|revenue|rev[\s-]?share)"
    r"|earn\s+(?:up\s+to\s+)?(\d{1,3})\s*%"
    r"|(?:返佣|佣金|分成|提成|返现|奖励)\s*(?:高达\s*)?(\d{1,3})\s*%"
    r"|(\d{1,3})\s*%\s*(?:返佣|佣金|分成|提成|返现)",
    re.I,
)

# Affiliate-network fingerprints -> platform name. Tells you which network to
# sign up through for a service's referral program.
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


def detect_affiliate_platform(html: str) -> str:
    """Pure: identify the affiliate network powering a site, or '' if none."""
    text = (html or "").lower()
    for sig, name in _AFFILIATE_SIGNATURES.items():
        if sig in text:
            return name
    return ""


def _links(soup: BeautifulSoup, base_url: str):
    """Yield (absolute_url, lowercased_anchor_text, lowercased_href)."""
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "javascript:", "#")):
            continue
        text = a.get_text(" ", strip=True).lower()
        yield urljoin(base_url, href), text, href.lower()


def _match(links, page_text, paths, texts):
    """Return matching URL (or '') if any path/anchor/page signal is present."""
    for url, anchor, href in links:
        if any(p in href for p in paths) or any(t == anchor or t in anchor for t in texts):
            return url
    # fallback: keyword present in page body (no specific link)
    return "" if not any(t in page_text for t in texts) else "__text__"


def extract_commission(text: str) -> str:
    m = _COMMISSION_RE.search(text or "")
    if not m:
        return ""
    pct = next((g for g in m.groups() if g), None)
    return f"{pct}%" if pct else ""


def analyze_html(html: str, base_url: str) -> dict:
    """Pure: inspect a rendered page and report capabilities found."""
    soup = BeautifulSoup(html, "html.parser")
    links = list(_links(soup, base_url))
    body_text = soup.get_text(" ", strip=True).lower()

    api_url = _match(links, body_text, API_PATHS, API_TEXT)
    ref_url = _match(links, body_text, REFERRAL_PATHS, REFERRAL_TEXT)
    price_url = _match(links, body_text, PRICING_PATHS, PRICING_TEXT)

    title = (soup.title.get_text(strip=True) if soup.title else "")
    desc_el = soup.find("meta", attrs={"name": "description"}) or \
        soup.find("meta", attrs={"property": "og:description"})
    description = desc_el.get("content", "").strip() if desc_el else ""
    og = soup.find("meta", attrs={"property": "og:image"})

    def clean(u: str) -> str:
        return "" if u in ("", "__text__") else u

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
    }


async def verify(url: str) -> dict:
    """Render `url` and analyze it. Returns findings (empty dict on failure)."""
    base = url if "://" in url else f"https://{url}"
    html = await render(base)
    if not html:
        # plain render blocked (Cloudflare etc.) — try the stealth browser once
        from .browser import render_stealth
        html = await render_stealth(base)
    if not html:
        return {}
    findings = analyze_html(html, base)
    return await _probe_missing(base, findings)


# Known paths to probe when the homepage doesn't surface a capability.
# Cheap httpx GETs (no browser); first that yields the signal wins.
_PROBE_PATHS = {
    "api": ["/docs", "/api", "/api-docs", "/developers", "/developer",
            "/reference", "/open", "/openapi"],
    "referral": ["/affiliate", "/affiliates", "/referral", "/partners",
                 "/partner", "/fenxiao", "/tuiguang", "/hehuoren"],
    "pricing": ["/pricing", "/plans", "/price", "/huiyuan", "/vip"],
}


def merge_findings(base: dict, probed: dict) -> dict:
    """Pure: fill missing capabilities in `base` from a probed page result."""
    out = dict(base)
    if not out.get("has_api") and probed.get("has_api"):
        out["has_api"] = True
        out["api_docs_url"] = probed.get("api_docs_url") or probed["__url__"]
    if not out.get("has_referral") and probed.get("has_referral"):
        out["has_referral"] = True
        out["referral_url"] = probed.get("referral_url") or probed["__url__"]
        if not out.get("referral_commission"):
            out["referral_commission"] = probed.get("referral_commission", "")
    if not out.get("affiliate_platform") and probed.get("affiliate_platform"):
        out["affiliate_platform"] = probed["affiliate_platform"]
    if not out.get("pricing_info") and probed.get("pricing_info"):
        out["pricing_info"] = "found"
        out["pricing_model"] = probed.get("pricing_model") or probed["__url__"]
    return out


async def _probe_missing(base_url: str, findings: dict) -> dict:
    """Probe known paths for capabilities the homepage didn't reveal."""
    from urllib.parse import urljoin

    import httpx
    needed = [cap for cap, key in (("api", "has_api"), ("referral", "has_referral"),
                                   ("pricing", "pricing_info"))
              if not findings.get(key)]
    if not needed:
        return findings
    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (ai-finder)"},
    ) as client:
        fails = 0  # consecutive connection failures -> circuit breaker
        for cap in needed:
            for path in _PROBE_PATHS[cap]:
                if fails >= 3:
                    return findings  # host is flaky/dead — stop wasting requests
                if findings.get({"api": "has_api", "referral": "has_referral",
                                 "pricing": "pricing_info"}[cap]):
                    break
                target = urljoin(base_url, path)
                try:
                    r = await client.get(target, timeout=8)
                except Exception:
                    fails += 1
                    continue
                fails = 0
                if r.status_code != 200 or not r.text:
                    continue
                probed = analyze_html(r.text, target)
                probed["__url__"] = target
                findings = merge_findings(findings, probed)
    return findings


def _persist_fields(row, findings: dict) -> dict:
    """Pure: build the DB update dict from findings (no I/O)."""
    import time
    fields = {"last_checked": time.time()}
    if findings:
        fields.update({
            "has_api": int(findings["has_api"]),
            "api_docs_url": findings["api_docs_url"],
            "has_referral": int(findings["has_referral"]),
            "referral_url": findings["referral_url"],
            "referral_commission": findings["referral_commission"],
            "affiliate_platform": findings.get("affiliate_platform", ""),
            "pricing_info": findings["pricing_info"],
            "pricing_model": findings["pricing_model"],
            "verified_at": time.time(),
            "status": "verified",
        })
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
    """Verify a stored service and persist the findings."""
    row = db.get(service_id)
    if not row:
        return {}
    findings = await verify(row["source_url"] or row["domain"])
    db.update_service(service_id, **_persist_fields(row, findings))
    return findings


async def verify_services_batch(db: DB, service_ids: list[int],
                                concurrency: int = 6) -> int:
    """Verify many services reusing ONE browser. Returns count processed.

    Renders all target URLs in a single browser instance (big speedup over
    one browser per site), then analyzes + persists each.
    """
    from .browser import render_many, render_stealth_many
    rows = [db.get(sid) for sid in service_ids]
    rows = [r for r in rows if r]
    urls = {r["id"]: _row_url(r) for r in rows}
    html_by_url = await render_many(list(urls.values()), concurrency=concurrency)
    # Stealth retry for sites plain render couldn't fetch (Cloudflare etc.),
    # batched into one shared stealth browser.
    blocked = [u for u in urls.values() if not html_by_url.get(u)]
    if blocked:
        html_by_url.update(await render_stealth_many(blocked))
    for r in rows:
        html = html_by_url.get(urls[r["id"]], "")
        findings = analyze_html(html, urls[r["id"]]) if html else {}
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
        print(f"  name:       {f['name']}")
        print(f"  api:        {f['has_api']}  {f['api_docs_url']}")
        print(f"  referral:   {f['has_referral']}  {f['referral_url']}  {f['referral_commission']}")
        print(f"  platform:   {f.get('affiliate_platform') or '-'}")
        print(f"  pricing:    {f['pricing_info']}  {f['pricing_model']}")
        print(f"  desc:       {f['description'][:100]}")
    asyncio.run(_main())
