"""Test the shared store_candidates collector helper."""
from ai_finder.collectors import store_candidates
from ai_finder.db import DB, Candidate


def test_store_candidates_persists_and_logs(tmp_path):
    db = DB(tmp_path / "t.db")
    cands = [Candidate(url="https://a.ai", source_platform="x"),
             Candidate(url="https://b.ai", source_platform="x")]
    new = store_candidates(db, "mysource", cands)
    assert new == 2
    assert db.stats()["total"] == 2
    rep = {r["source"]: r for r in db.source_report()}
    assert rep["mysource"]["candidates"] == 2
    assert rep["mysource"]["new_services"] == 2
    db.close()


def test_store_candidates_counts_only_new(tmp_path):
    db = DB(tmp_path / "t.db")
    store_candidates(db, "s", [Candidate(url="https://a.ai", source_platform="s")])
    new = store_candidates(db, "s", [Candidate(url="https://a.ai/x", source_platform="s")])
    assert new == 0
    db.close()
