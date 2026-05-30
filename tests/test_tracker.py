"""Tests for freshness tracker (diff_fields pure + recheck with mocked verify)."""
import asyncio

from ai_finder.db import DB, Candidate
from ai_finder.tracker import diff_fields, recheck_all, recheck_service


def test_diff_fields_detects_changes():
    old = {"has_api": 1, "has_referral": 0, "referral_commission": "",
           "status": "verified"}
    new = {"has_api": 1, "has_referral": 1, "referral_commission": "30%",
           "status": "verified"}
    changes = dict((c[0], (c[1], c[2])) for c in diff_fields(old, new))
    assert "has_referral" in changes and changes["has_referral"] == ("0", "1")
    assert changes["referral_commission"] == ("", "30%")
    assert "has_api" not in changes


def test_diff_fields_no_change():
    row = {"has_api": 1, "has_referral": 1, "referral_commission": "20%",
           "status": "verified"}
    assert diff_fields(row, dict(row)) == []


def test_recheck_records_history(tmp_path, monkeypatch):
    db = DB(tmp_path / "t.db")
    sid, _ = db.upsert_candidate(Candidate(url="https://x.ai", source_platform="hn"))
    db.update_service(sid, status="verified", has_api=1, has_referral=0)

    async def fake_verify(url):
        return {"has_api": True, "has_referral": True,
                "referral_commission": "40%"}
    monkeypatch.setattr("ai_finder.tracker.verify", fake_verify)

    changes = asyncio.run(recheck_service(db, sid))
    fields = {c[0] for c in changes}
    assert "has_referral" in fields
    hist = db.conn.execute(
        "SELECT field,new_value FROM service_history WHERE service_id=?",
        (sid,)).fetchall()
    assert any(h["field"] == "has_referral" and h["new_value"] == "1"
               for h in hist)
    db.close()


def test_recheck_detects_dead_site(tmp_path, monkeypatch):
    db = DB(tmp_path / "t.db")
    sid, _ = db.upsert_candidate(Candidate(url="https://gone.ai", source_platform="hn"))
    db.update_service(sid, status="verified", has_api=1)

    async def fake_verify(url):
        return {}  # unreachable
    monkeypatch.setattr("ai_finder.tracker.verify", fake_verify)

    report = asyncio.run(recheck_all(db))
    assert "gone.ai" in report
    assert db.get(sid)["status"] == "unreachable"
    db.close()
