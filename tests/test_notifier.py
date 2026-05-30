"""Tests for Telegram notifier (pure formatting + gating, no network)."""
import asyncio

from ai_finder.db import DB, Candidate
from ai_finder.notifier import format_service, notify_new


def test_format_includes_key_fields():
    row = {"name": "GeekAI", "domain": "geekai.co", "score": 95,
           "category": "text", "description": "LLM gateway",
           "has_api": 1, "api_docs_url": "https://geekai.co/docs",
           "has_referral": 1, "referral_commission": "30%",
           "referral_url": "https://geekai.co/aff"}
    msg = format_service(row)
    assert "GeekAI" in msg and "score 95" in msg
    assert "geekai.co/docs" in msg
    assert "30%" in msg and "geekai.co/aff" in msg


def test_format_escapes_html():
    row = {"name": "<b>x</b>", "domain": "x.ai", "score": 1}
    assert "<b>x</b>" not in format_service(row).split("\n", 1)[1]


def test_notify_new_no_token_returns_zero(tmp_path):
    db = DB(tmp_path / "t.db")
    assert asyncio.run(notify_new(db, "", "", 50)) == 0
    db.close()


def test_notify_new_gates_and_marks(tmp_path, monkeypatch):
    db = DB(tmp_path / "t.db")
    hi, _ = db.upsert_candidate(Candidate(url="https://hi.ai", source_platform="hn"))
    db.update_service(hi, status="verified", score=80, name="Hi")
    lo, _ = db.upsert_candidate(Candidate(url="https://lo.ai", source_platform="hn"))
    db.update_service(lo, status="verified", score=10, name="Lo")

    sent_msgs = []

    async def fake_send(token, chat, text):
        sent_msgs.append(text)
        return True
    monkeypatch.setattr("ai_finder.notifier.send_message", fake_send)

    n = asyncio.run(notify_new(db, "tok", "chat", threshold=50))
    assert n == 1
    assert db.get(hi)["status"] == "notified"
    assert db.get(lo)["status"] == "verified"  # below threshold, untouched
    # second run sends nothing (already notified)
    assert asyncio.run(notify_new(db, "tok", "chat", threshold=50)) == 0
    db.close()
