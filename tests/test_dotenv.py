"""Tests for .env loading (no real env mutation leakage)."""
import os

from ai_finder.config import load, load_dotenv


def test_load_dotenv_parses(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        '# comment\n\nAPIFY_TOKEN="tok123"\nTELEGRAM_CHAT_ID=42\nBAD LINE\n')
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    n = load_dotenv(env)
    assert n == 2
    assert os.environ["APIFY_TOKEN"] == "tok123"   # quotes stripped
    assert os.environ["TELEGRAM_CHAT_ID"] == "42"


def test_load_dotenv_does_not_override_existing(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("APIFY_TOKEN=fromfile\n")
    monkeypatch.setenv("APIFY_TOKEN", "fromenv")
    load_dotenv(env)
    assert os.environ["APIFY_TOKEN"] == "fromenv"  # env wins


def test_load_dotenv_missing_file_ok(tmp_path):
    assert load_dotenv(tmp_path / "nope.env") == 0


def test_load_uses_dotenv_for_secrets(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("APIFY_TOKEN=secretfromenv\n")
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)  # load() reads .env from cwd
    cfg = load(tmp_path / "none.toml")
    assert cfg["apify"]["token"] == "secretfromenv"
