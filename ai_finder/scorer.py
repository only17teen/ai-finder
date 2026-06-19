"""Scoring + categorization for discovered services.

Pure scoring/categorization functions, plus a `rescore_all` that applies them
to every stored service. Score reflects monetization potential (API + referral
+ commission) and technical density (framework artifacts).
"""

from __future__ import annotations

import re
from typing import Any

from .db import DB

# category -> keywords (checked against name + description)
CATEGORIES = {
    "image": ["image", "photo", "art", "diffusion", "avatar", "logo", "design"],
    "video": ["video", "animation", "avatar video", "clip", "film"],
    "audio": ["audio", "voice", "speech", "music", "tts", "transcribe", "podcast"],
    "code": ["code", "coding", "developer", "ide", "programming", "devtool"],
    "text": ["text", "writing", "copy", "chat", "chatbot", "summar", "content"],
    "translation": ["translate", "translation", "localization", "language"],
    "data": ["data", "scrape", "analytics", "database", "search", "rag"],
    "automation": ["automation", "agent", "workflow", "bot", "rpa"],
}


def categorize(name: str, description: str, current_cat: str = "") -> str:
    """Return the best-matching category. Prefers current_cat if it exists."""
    if current_cat and current_cat != "other":
        return current_cat

    text = f"{name} {description}".lower()
    best, best_hits = "other", 0
    for cat, kws in CATEGORIES.items():
        hits = sum(1 for kw in kws if kw in text)
        if hits > best_hits:
            best, best_hits = cat, hits
    return best


def _commission_pct(commission: str) -> int:
    m = re.search(r"(\d{1,3})", commission or "")
    return int(m.group(1)) if m else 0


def score_service(row: dict[str, Any]) -> int:
    """Compute an elite monetization-potential score.

    Composition (capped at 115):
        Monetization Baseline:     55 max (api 30 + referral 25)
        Commission Bonus:          20 max (>=30%: 20, >15%: 10)
        Technical Density:         30 max (stacks: 5/each cap 20, +10 high-value)
        Market Corroboration:      30 max (multi-platform 15, niche 15)
        Popularity:                15 max (upvotes/100 * 5, capped at 15)
        Pricing transparency:      10 max

    Niche and multi-platform bonuses are mutually exclusive on the same axis
    (a service with 1 platform and low upvotes gets the niche bonus; with 2+,
    it gets the multi-platform bonus instead). Niche requires monetization so
    a low-value, non-monetizable service does not jump the ranking.
    """
    s = 0

    # 1. Monetization Baseline (Max 55)
    if row.get("has_api"):
        s += 30
    if row.get("has_referral"):
        s += 25
    monetizable = bool(row.get("has_api")) or bool(row.get("has_referral"))

    # 2. Commission Bonus (Max 20)
    comm = _commission_pct(row.get("referral_commission", ""))
    if comm >= 30:
        s += 20
    elif comm > 15:
        s += 10

    # 3. Technical Density (Max 30)
    stacks = set(filter(None, (row.get("tech_stack") or "").split(",")))
    if stacks:
        high_value = {"vercel-ai", "langchain", "openai-compatible", "dify"}
        s += min(20, len(stacks) * 5)
        if stacks & high_value:
            s += 10

    # 4. Market Corroboration & Niche Signal (Max 30)
    platforms = [p for p in (row.get("platforms") or "").split(",") if p]
    upvotes = int(row.get("upvotes", 0) or 0)

    if len(platforms) >= 2:
        s += 15  # multi-platform validation
    elif len(platforms) == 1 and upvotes < 50 and monetizable:
        s += 15  # alpha-niche discovery bonus (requires monetization)

    # 5. Popularity (Max 15) - soft signal
    if upvotes > 0:
        s += min(15, (upvotes // 100) * 5)

    # 6. Pricing transparency (Max 10)
    if row.get("pricing_info") == "found":
        s += 10

    return s


def rescore_all(db: DB) -> int:
    """Recompute score + category for every service. Returns count updated."""
    n = 0
    for row in db.all_services():
        d = dict(row)
        score = score_service(d)
        cat = categorize(
            d.get("name", "") or "", d.get("description", "") or "", d.get("category", "")
        )
        db.update_service(row["id"], score=score, category=cat)
        db.add_tag(row["id"], cat)
        n += 1
    return n


if __name__ == "__main__":
    db = DB()
    updated = rescore_all(db)
    print(f"Rescored {updated} services. Top 20 Elite:")
    for r in db.top(20):
        stacks = r.get("tech_stack") or "-"
        print(
            f"  [{r['score']:>3}] {r['category']:<11} {r['domain']:<28} "
            f"api={r['has_api']} ref={r['has_referral']} tech={stacks}"
        )
    db.close()
