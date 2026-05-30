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


def test_stats(db):
    db.upsert_candidate(Candidate(url="https://a.com", source_platform="hn"))
    sid, _ = db.upsert_candidate(
        Candidate(url="https://b.com", source_platform="hn"))
    db.update_service(sid, has_api=1, status="verified")
    s = db.stats()
    assert s["total"] == 2 and s["with_api"] == 1 and s["verified"] == 1
