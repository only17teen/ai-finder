"""Tests for db module."""
import pytest

from ai_finder.db import DB, Candidate, domain_of


@pytest.fixture
def db(tmp_path):
    d = DB(tmp_path / "test.db")
    yield d
    d.close()


def test_domain_of_normalizes():
    assert domain_of("https://www.GeekAI.co/path?x=1") == "geekai.co"
    assert domain_of("geekai.co") == "geekai.co"
    assert domain_of("http://sub.example.com") == "sub.example.com"


def test_domain_of_multilevel_tld():
    assert domain_of("https://foo.com.cn") == "foo.com.cn"
    assert domain_of("https://www.foo.co.uk") == "foo.co.uk"
    assert domain_of("https://app.bar.co.kr") == "bar.co.kr"
    assert domain_of("https://api.baz.com.cn/v1") == "baz.com.cn"
    assert domain_of("https://example.co.uk") == "example.co.uk"


def test_domain_of_strips_common_subdomains():
    # near-duplicates collapse to the registrable domain
    assert domain_of("https://app.klingai.com") == "klingai.com"
    assert domain_of("https://docs.docmee.cn") == "docmee.cn"
    assert domain_of("https://api.openai.com/v1") == "openai.com"
    assert domain_of("https://developer.x.ai") == "x.ai"
    # meaningful subdomains are preserved
    assert domain_of("https://jimeng.jianying.com") == "jimeng.jianying.com"
    # never strip below 2 labels
    assert domain_of("https://app.io") == "app.io"


def test_dedup_collapses_subdomain_variants(db):
    a, new_a = db.upsert_candidate(
        Candidate(url="https://klingai.com", source_platform="hn", upvotes=5))
    b, new_b = db.upsert_candidate(
        Candidate(url="https://app.klingai.com/create", source_platform="ph",
                  upvotes=20))
    assert a == b and new_a is True and new_b is False
    row = db.get(a)
    assert row["upvotes"] == 20
    assert "hn" in row["platforms"] and "ph" in row["platforms"]


def test_schema_created(db):
    tables = {r[0] for r in db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"services", "sources_log", "tags", "service_history"} <= tables


def test_insert_and_read(db):
    sid, new = db.upsert_candidate(
        Candidate(url="https://geekai.co", name="GeekAI", source_platform="hn"))
    assert new is True
    row = db.get(sid)
    assert row["domain"] == "geekai.co"
    assert row["name"] == "GeekAI"
    assert row["status"] == "pending"


def test_dedup_by_domain(db):
    sid1, new1 = db.upsert_candidate(
        Candidate(url="https://geekai.co/a", source_platform="hn", upvotes=10))
    sid2, new2 = db.upsert_candidate(
        Candidate(url="https://www.geekai.co/b", source_platform="ph",
                  upvotes=50))
    assert sid1 == sid2
    assert new1 is True and new2 is False
    row = db.get(sid1)
    assert row["upvotes"] == 50  # max kept
    assert "hn" in row["platforms"] and "ph" in row["platforms"]


def test_update_and_tags(db):
    sid, _ = db.upsert_candidate(
        Candidate(url="https://x.ai", source_platform="hn"))
    db.update_service(sid, has_api=1, status="verified", score=55)
    db.add_tag(sid, "code")
    db.add_tag(sid, "code")  # idempotent
    row = db.get(sid)
    assert row["has_api"] == 1 and row["status"] == "verified"
    tags = [r["tag"] for r in db.conn.execute(
        "SELECT tag FROM tags WHERE service_id=?", (sid,))]
    assert tags == ["code"]


def test_search(db):
    a, _ = db.upsert_candidate(Candidate(url="https://imagegen.ai",
                                         name="ImageGen", source_platform="hn"))
    db.update_service(a, category="image", score=70, description="AI art tool")
    b, _ = db.upsert_candidate(Candidate(url="https://codehelper.dev",
                                         name="CodeHelper", source_platform="hn"))
    db.update_service(b, category="code", score=30, description="coding agent")

    assert {r["domain"] for r in db.search(keyword="image")} == {"imagegen.ai"}
    assert {r["domain"] for r in db.search(keyword="agent")} == {"codehelper.dev"}
    assert {r["domain"] for r in db.search(category="code")} == {"codehelper.dev"}
    assert {r["domain"] for r in db.search(min_score=50)} == {"imagegen.ai"}
    rows = db.search(min_score=0)
    assert [r["domain"] for r in rows] == ["imagegen.ai", "codehelper.dev"]


def test_delete_services(db):
    a, _ = db.upsert_candidate(Candidate(url="https://live.ai", source_platform="hn"))
    db.update_service(a, status="verified")
    d, _ = db.upsert_candidate(Candidate(url="https://dead.ai", source_platform="hn"))
    db.update_service(d, status="unreachable")
    db.add_tag(d, "code")
    db.record_change(d, "status", "verified", "unreachable")

    removed = db.delete_services("unreachable")
    assert removed == 1
    assert db.get(d) is None
    assert db.get(a) is not None
    assert db.conn.execute(
        "SELECT COUNT(*) FROM tags WHERE service_id=?", (d,)).fetchone()[0] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM service_history WHERE service_id=?",
        (d,)).fetchone()[0] == 0
    assert db.delete_services("unreachable") == 0


def test_stale_unreachable(db):
    import time
    now = time.time()
    old, _ = db.upsert_candidate(Candidate(url="https://old.ai", source_platform="hn"))
    db.update_service(old, status="unreachable", last_checked=now - 100000)
    fresh, _ = db.upsert_candidate(Candidate(url="https://fresh.ai", source_platform="hn"))
    db.update_service(fresh, status="unreachable", last_checked=now - 10)
    ok, _ = db.upsert_candidate(Candidate(url="https://ok.ai", source_platform="hn"))
    db.update_service(ok, status="verified", last_checked=now - 100000)
    due = db.stale_unreachable(24 * 3600, now=now)
    assert {r["domain"] for r in due} == {"old.ai"}


def test_source_report(db):
    db.log_source("hackernews", 10, 3)
    db.log_source("hackernews", 8, 2)
    db.log_source("reddit", 20, 7)
    rows = {r["source"]: r for r in db.source_report()}
    assert rows["hackernews"]["runs"] == 2
    assert rows["hackernews"]["candidates"] == 18
    assert rows["hackernews"]["new_services"] == 5
    assert db.source_report()[0]["source"] == "reddit"  # ordered by new desc


def test_monetizable(db):
    a, _ = db.upsert_candidate(Candidate(url="https://earn.ai", source_platform="hn"))
    db.update_service(a, has_referral=1, score=80, referral_url="https://earn.ai/aff")
    b, _ = db.upsert_candidate(Candidate(url="https://noref.ai", source_platform="hn"))
    db.update_service(b, has_referral=0, has_api=1, score=90)
    c, _ = db.upsert_candidate(Candidate(url="https://low.ai", source_platform="hn"))
    db.update_service(c, has_referral=1, score=20)
    rows = db.monetizable()
    assert [r["domain"] for r in rows] == ["earn.ai", "low.ai"]


def test_get_history(db):
    sid, _ = db.upsert_candidate(Candidate(url="https://x.ai", source_platform="hn"))
    db.record_change(sid, "has_referral", "0", "1")
    db.record_change(sid, "referral_commission", "", "30%")
    rows = db.get_history("x.ai")
    assert len(rows) == 2
    assert rows[0]["field"] == "has_referral"
    assert rows[1]["new_value"] == "30%"
    assert db.get_history("nope.ai") == []


def test_upsert_candidates_batch(db):
    cands = [Candidate(url="https://a.ai", source_platform="x"),
             Candidate(url="https://b.ai", source_platform="y"),
             Candidate(url="https://github.com/x", source_platform="z"),  # noise
             Candidate(url="https://a.ai/dup", source_platform="w")]      # dup
    new = db.upsert_candidates(cands)
    assert new == 2  # a.ai, b.ai (noise skipped, dup merged)
    assert db.stats()["total"] == 2
    row = db.conn.execute(
        "SELECT platforms FROM services WHERE domain='a.ai'").fetchone()
    assert "x" in row["platforms"] and "w" in row["platforms"]


def test_stats(db):
    db.upsert_candidate(Candidate(url="https://a.com", source_platform="hn"))
    sid, _ = db.upsert_candidate(
        Candidate(url="https://b.com", source_platform="hn"))
    db.update_service(sid, has_api=1, status="verified")
    s = db.stats()
    assert s["total"] == 2 and s["with_api"] == 1 and s["verified"] == 1
