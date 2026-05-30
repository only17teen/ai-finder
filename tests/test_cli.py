"""Tests for config loading and CLI commands (no network)."""
import csv

from ai_finder import config as cfgmod
from ai_finder.db import DB, Candidate
from ai_finder import main as cli


def test_config_defaults_when_missing(tmp_path):
    cfg = cfgmod.load(tmp_path / "nope.toml")
    assert cfg["sources"]["hackernews"] is True
    assert cfg["db_path"] == "ai_finder.db"


def test_config_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "secret123")
    cfg = cfgmod.load(tmp_path / "nope.toml")
    assert cfg["apify"]["token"] == "secret123"


def test_config_file_merge(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('db_path = "x.db"\n[sources]\nhackernews = false\n')
    cfg = cfgmod.load(p)
    assert cfg["db_path"] == "x.db"
    assert cfg["sources"]["hackernews"] is False
    assert cfg["sources"]["github_trending"] is True  # default preserved


def test_export_filters_api_and_referral(tmp_path):
    db = DB(tmp_path / "t.db")
    good, _ = db.upsert_candidate(Candidate(url="https://good.ai", name="Good",
                                            source_platform="hn"))
    db.update_service(good, has_api=1, has_referral=1, score=80,
                      category="code", referral_commission="30%")
    bad, _ = db.upsert_candidate(Candidate(url="https://bad.ai", source_platform="hn"))
    db.update_service(bad, has_api=1, has_referral=0)  # no referral -> excluded
    out = tmp_path / "out.csv"
    cli.cmd_export(db, str(out))
    rows = list(csv.DictReader(open(out)))
    assert len(rows) == 1 and rows[0]["domain"] == "good.ai"
    assert rows[0]["referral_commission"] == "30%"
    db.close()


def test_cli_status_runs(tmp_path, capsys):
    dbfile = tmp_path / "s.db"
    DB(dbfile).close()
    rc = cli.main(["--config", str(tmp_path / "none.toml"), "status"])
    # default db_path points elsewhere; just assert clean exit + output format
    assert rc == 0
    assert "total=" in capsys.readouterr().out


def test_cli_top_runs(tmp_path, capsys, monkeypatch):
    # point config db_path at a temp db with one row
    cfile = tmp_path / "c.toml"
    dbfile = tmp_path / "top.db"
    cfile.write_text(f'db_path = "{dbfile}"\n')
    db = DB(dbfile)
    sid, _ = db.upsert_candidate(Candidate(url="https://a.ai", name="A",
                                           source_platform="hn"))
    db.update_service(sid, score=42, category="code", has_api=1)
    db.close()
    rc = cli.main(["--config", str(cfile), "top", "--limit", "5"])
    assert rc == 0
    assert "a.ai" in capsys.readouterr().out
