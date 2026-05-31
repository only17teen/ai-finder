"""Tests for config loading and CLI commands (no network)."""
import csv

from ai_finder import config as cfgmod
from ai_finder import main as cli
from ai_finder.db import DB, Candidate


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


def test_collect_isolates_source_failure(tmp_path, monkeypatch):
    """A failing collector must not abort the others; totals still sum."""
    import asyncio
    db = DB(tmp_path / "t.db")
    cfg = cfgmod.load(tmp_path / "none.toml")

    async def ok(*a, **k):
        return 3

    async def boom(*a, **k):
        raise RuntimeError("source down")

    monkeypatch.setattr(cli.pipeline.hackernews, "collect", ok)
    monkeypatch.setattr(cli.pipeline.reddit_rss, "collect", boom)
    # disable everything except the two we control
    for s in cfg["sources"]:
        cfg["sources"][s] = s in ("hackernews", "reddit")

    total = asyncio.run(cli._collect(db, cfg, only=None))
    assert total == 3  # ok counted, boom logged + skipped
    db.close()


def test_export_all_and_min_score(tmp_path):
    db = DB(tmp_path / "t.db")
    # api+referral, high score
    a, _ = db.upsert_candidate(Candidate(url="https://a.ai", name="A",
                                         source_platform="hn"))
    db.update_service(a, has_api=1, has_referral=1, score=80)
    # api only, mid score
    b, _ = db.upsert_candidate(Candidate(url="https://b.ai", name="B",
                                         source_platform="hn"))
    db.update_service(b, has_api=1, has_referral=0, score=40)
    # api only, low score
    c, _ = db.upsert_candidate(Candidate(url="https://c.ai", name="C",
                                         source_platform="hn"))
    db.update_service(c, has_api=1, has_referral=0, score=10)

    # default: only api+referral -> just A
    out1 = tmp_path / "default.csv"
    cli.cmd_export(db, str(out1))
    assert {r["domain"] for r in csv.DictReader(open(out1))} == {"a.ai"}

    # --all with min-score 30 -> A and B (C filtered by score)
    out2 = tmp_path / "all.csv"
    cli.cmd_export(db, str(out2), min_score=30, require_referral=False)
    domains = [r["domain"] for r in csv.DictReader(open(out2))]
    assert domains == ["a.ai", "b.ai"]  # sorted by score desc
    db.close()


def test_cli_sources_lists(tmp_path, capsys):
    cfile = tmp_path / "c.toml"
    cfile.write_text('[sources]\nhackernews = true\nreddit = false\n')
    rc = cli.main(["--config", str(cfile), "sources"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[on ] hackernews" in out
    assert "[off] reddit" in out


def test_cli_run_rejects_invalid_source():
    import pytest
    with pytest.raises(SystemExit):
        cli.main(["run", "--source", "nonsense"])


def test_cli_top_json(tmp_path, capsys):
    import json
    cfile = tmp_path / "c.toml"
    dbfile = tmp_path / "j.db"
    cfile.write_text(f'db_path = "{dbfile}"\n')
    db = DB(dbfile)
    sid, _ = db.upsert_candidate(Candidate(url="https://a.ai", name="A",
                                           source_platform="hn"))
    db.update_service(sid, score=42, category="code", has_api=1)
    db.close()
    rc = cli.main(["--config", str(cfile), "top", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["domain"] == "a.ai" and data[0]["score"] == 42


def test_cli_status_json(tmp_path, capsys):
    import json
    cfile = tmp_path / "c.toml"
    dbfile = tmp_path / "s.db"
    cfile.write_text(f'db_path = "{dbfile}"\n')
    DB(dbfile).close()
    rc = cli.main(["--config", str(cfile), "status", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {"total", "pending", "verified", "with_api", "with_referral"}


def test_cli_recheck_reports_changes(tmp_path, capsys, monkeypatch):
    cfile = tmp_path / "c.toml"
    dbfile = tmp_path / "r.db"
    cfile.write_text(f'db_path = "{dbfile}"\n')
    db = DB(dbfile)
    sid, _ = db.upsert_candidate(Candidate(url="https://x.ai", source_platform="hn"))
    db.update_service(sid, status="verified", has_referral=0)  # last_checked NULL
    db.close()

    async def fake_verify(url):
        return {"has_api": True, "has_referral": True,
                "referral_commission": "40%"}
    monkeypatch.setattr("ai_finder.tracker.verify", fake_verify)

    rc = cli.main(["--config", str(cfile), "recheck"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "x.ai" in out and "has_referral" in out


def test_cli_digest(tmp_path, capsys, monkeypatch):
    cfile = tmp_path / "c.toml"
    dbfile = tmp_path / "d.db"
    cfile.write_text(f'db_path = "{dbfile}"\n[telegram]\nbot_token = "t"\nchat_id = "c"\n')
    DB(dbfile).close()

    async def fake_send_digest(db, token, chat, limit):
        assert token == "t" and chat == "c"
        return True
    monkeypatch.setattr("ai_finder.notifier.send_digest", fake_send_digest)

    rc = cli.main(["--config", str(cfile), "digest", "--limit", "5"])
    assert rc == 0
    assert "Digest sent." in capsys.readouterr().out


def test_export_json_and_md(tmp_path):
    import json
    db = DB(tmp_path / "t.db")
    a, _ = db.upsert_candidate(Candidate(url="https://a.ai", name="A",
                                         source_platform="hn"))
    db.update_service(a, has_api=1, has_referral=1, score=80, category="code",
                      referral_commission="30%", referral_url="https://a.ai/aff")
    # JSON
    j = tmp_path / "out.json"
    cli.cmd_export(db, str(j), fmt="json")
    data = json.loads(j.read_text())
    assert data[0]["domain"] == "a.ai" and data[0]["referral_commission"] == "30%"
    # Markdown
    m = tmp_path / "out.md"
    cli.cmd_export(db, str(m), fmt="md")
    text = m.read_text()
    assert text.startswith("| domain |")
    assert "a.ai" in text and "---" in text
    db.close()


def test_cli_links_shows_platform(tmp_path, capsys):
    cfile = tmp_path / "c.toml"
    dbfile = tmp_path / "lp.db"
    cfile.write_text(f'db_path = "{dbfile}"\n')
    db = DB(dbfile)
    sid, _ = db.upsert_candidate(Candidate(url="https://earn.ai", name="EarnAI",
                                           source_platform="hn"))
    db.update_service(sid, has_referral=1, score=80,
                      referral_url="https://earn.ai/aff",
                      affiliate_platform="Rewardful")
    db.close()
    rc = cli.main(["--config", str(cfile), "links"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "via Rewardful" in out and "earn.ai/aff" in out


def test_cmd_run_uses_verify_config(tmp_path, monkeypatch):
    import asyncio
    db = DB(tmp_path / "t.db")
    cfg = cfgmod.load(tmp_path / "none.toml")
    cfg["verify"] = {"concurrency": 3, "retry_cooldown_h": 12.0}
    for s in cfg["sources"]:
        cfg["sources"][s] = False  # skip collection

    captured = {}

    async def fake_verify_pending(db_, concurrency, retry_cooldown_h, max_verify):
        captured["concurrency"] = concurrency
        captured["cooldown"] = retry_cooldown_h
        captured["max_verify"] = max_verify
        return 0
    monkeypatch.setattr(cli, "_verify_pending", fake_verify_pending)

    asyncio.run(cli.cmd_run(db, cfg, only=None))
    assert captured == {"concurrency": 3, "cooldown": 12.0, "max_verify": 100}
    db.close()


def test_monetizable_referral_urls(tmp_path):
    db = DB(tmp_path / "t.db")
    a, _ = db.upsert_candidate(Candidate(url="https://a.ai", source_platform="hn"))
    db.update_service(a, has_referral=1, score=90, referral_url="https://a.ai/aff")
    b, _ = db.upsert_candidate(Candidate(url="https://b.ai", source_platform="hn"))
    db.update_service(b, has_referral=1, score=50, referral_url="https://b.ai/aff")
    c, _ = db.upsert_candidate(Candidate(url="https://c.ai", source_platform="hn"))
    db.update_service(c, has_referral=1, score=70)  # no referral_url -> skipped
    urls = cli.monetizable_referral_urls(db, limit=5)
    assert urls == ["https://a.ai/aff", "https://b.ai/aff"]  # score order, no None
    assert cli.monetizable_referral_urls(db, limit=1) == ["https://a.ai/aff"]
    db.close()


def test_cmd_open_calls_browser(tmp_path, monkeypatch, capsys):
    db = DB(tmp_path / "t.db")
    a, _ = db.upsert_candidate(Candidate(url="https://a.ai", source_platform="hn"))
    db.update_service(a, has_referral=1, score=90, referral_url="https://a.ai/aff")
    opened = []
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda u: opened.append(u))
    cli.cmd_open(db, limit=5)
    assert opened == ["https://a.ai/aff"]
    db.close()


def test_verify_pending_caps_at_max(tmp_path, monkeypatch):
    import asyncio

    from ai_finder import pipeline
    from ai_finder import verifier as v
    db = DB(tmp_path / "t.db")
    for i in range(5):
        db.upsert_candidate(Candidate(url=f"https://s{i}.ai", source_platform="hn"))

    captured = {}

    async def fake_batch(db_, ids, concurrency=6):
        captured["n"] = len(ids)
        return len(ids)
    monkeypatch.setattr(v, "verify_services_batch", fake_batch)

    asyncio.run(pipeline.verify_pending(db, max_verify=2))
    assert captured["n"] == 2   # only 2 of 5 pending verified this run
    db.close()
