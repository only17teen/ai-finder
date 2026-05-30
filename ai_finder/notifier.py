"""Telegram Bot notifications for new high-score finds.

`format_service` is pure/tested. `notify_new` sends services scoring above a
threshold that haven't been announced yet (tracked via status='notified').
Uses the Bot HTTP API (bot token + chat id) — no extra deps.
"""
from __future__ import annotations

import html

import httpx

from .db import DB

API = "https://api.telegram.org/bot{token}/sendMessage"


def format_service(row: dict) -> str:
    """Pure: HTML-formatted Telegram message for one service."""
    e = html.escape
    name = e(row.get("name") or row.get("domain", ""))
    lines = [f"<b>🤖 {name}</b>  (score {row.get('score', 0)})",
             f"🌐 {e(row.get('domain', ''))}"]
    if row.get("category"):
        lines.append(f"🏷 {e(row['category'])}")
    if row.get("description"):
        lines.append(e(row["description"][:200]))
    if row.get("has_api"):
        lines.append(f"🔌 API: {e(row.get('api_docs_url') or 'yes')}")
    if row.get("has_referral"):
        comm = row.get("referral_commission") or ""
        lines.append(f"💰 Referral{(' ' + comm) if comm else ''}: "
                     f"{e(row.get('referral_url') or 'yes')}")
    if row.get("pricing_model"):
        lines.append(f"💵 Pricing: {e(row['pricing_model'])}")
    return "\n".join(lines)


async def send_message(token: str, chat_id: str, text: str) -> bool:
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(
                API.format(token=token),
                json={"chat_id": chat_id, "text": text,
                      "parse_mode": "HTML",
                      "disable_web_page_preview": True},
                timeout=15,
            )
            return r.status_code == 200
        except Exception:
            return False


async def notify_new(db: DB, token: str, chat_id: str,
                     threshold: int = 50) -> int:
    """Announce verified services scoring >= threshold not yet notified.

    Marks them status='notified'. Returns count sent.
    """
    if not (token and chat_id):
        return 0
    rows = db.conn.execute(
        "SELECT * FROM services WHERE status='verified' AND score>=? "
        "ORDER BY score DESC", (threshold,),
    ).fetchall()
    sent = 0
    for row in rows:
        if await send_message(token, chat_id, format_service(dict(row))):
            db.update_service(row["id"], status="notified")
            sent += 1
    return sent


async def send_digest(db: DB, token: str, chat_id: str,
                      limit: int = 10) -> bool:
    """Send a top-N digest of the highest-scoring services."""
    if not (token and chat_id):
        return False
    rows = db.top(limit)
    if not rows:
        return False
    body = "\n\n".join(format_service(dict(r)) for r in rows)
    return await send_message(token, chat_id, f"<b>📊 AI Finder digest</b>\n\n{body}")


if __name__ == "__main__":
    sample = {"name": "GeekAI", "domain": "geekai.co", "score": 95,
              "category": "text", "description": "Unified LLM gateway API.",
              "has_api": 1, "api_docs_url": "https://geekai.co/docs",
              "has_referral": 1, "referral_commission": "30%",
              "referral_url": "https://geekai.co/affiliate",
              "pricing_model": "https://geekai.co/pricing"}
    print("Formatted message preview:\n")
    print(format_service(sample))
    print("\nSet bot token + chat_id in config to send live.")
