"""Scoring + categorization for discovered services.

Pure scoring/categorization functions, plus a `rescore_all` that applies them
to every stored service. Score reflects monetization potential (API + referral
+ commission) and corroboration across platforms.
"""
from __future__ import annotations

import re

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


def categorize(name: str, description: str) -> str:
    """Return the best-matching category, or 'other'."""
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


def score_service(row: dict) -> int:
    """Compute a monetization-potential score from a service row (pure)."""
    s = 0
    if row.get("has_api"):
        s += 30
    if row.get("has_referral"):
        s += 25
    if _commission_pct(row.get("referral_commission", "")) > 20:
        s += 20
    platforms = [p for p in (row.get("platforms") or "").split(",") if p]
    if len(platforms) >= 2:
        s += 15
    if "free" in (row.get("pricing_info", "") or "").lower() or \
            "free" in (row.get("pricing_model", "") or "").lower():
        s += 10
    s += 5 * (int(row.get("upvotes", 0) or 0) // 100)
    return s


def rescore_all(db: DB) -> int:
    """Recompute score + category for every service. Returns count updated."""
    n = 0
    for row in db.all_services():
        d = dict(row)
        score = score_service(d)
        cat = categorize(d.get("name", "") or "", d.get("description", "") or "")
        db.update_service(row["id"], score=score, category=cat)
        db.add_tag(row["id"], cat)
        n += 1
    return n


if __name__ == "__main__":
    db = DB()
    updated = rescore_all(db)
    print(f"Rescored {updated} services. Top 20:")
    for r in db.top(20):
        print(f"  [{r['score']:>3}] {r['category']:<11} {r['domain']:<28} "
              f"api={r['has_api']} ref={r['has_referral']}")
    db.close()
