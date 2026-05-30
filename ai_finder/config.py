"""Config loading from config.toml with env-var fallback for secrets."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config.toml"

DEFAULTS = {
    "db_path": "ai_finder.db",
    "sources": {  # enable/disable each collector
        "hackernews": True, "linux_forums": True, "apify": False,
        "ai_directories": True, "github_trending": True, "telegram": False,
        "hidden_gems": True, "foss": True, "forums": True,
        "asian_dev": True, "launch": True, "reddit": True,
        "intl_forums": True, "mastodon": True,
    },
    "limits": {"hackernews": 100, "github_trending": 25},
    "rate": {"per_domain_delay": 1.0, "max_retries": 3},
    "verify": {"concurrency": 6, "retry_cooldown_h": 24.0},
    "notify": {"threshold": 50},
    "apify": {"token": ""},
    "telegram": {"api_id": 0, "api_hash": "", "channels": [],
                 "bot_token": "", "chat_id": ""},
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(
            base.get(k), dict) else v
    return out


def load_dotenv(path: str | Path = ".env") -> int:
    """Load KEY=VALUE lines from a .env file into os.environ.

    Minimal parser, no dependency. Skips blanks/comments; strips surrounding
    quotes; does NOT overwrite vars already set in the environment. Returns the
    number of keys loaded.
    """
    p = Path(path)
    if not p.exists():
        return 0
    loaded = 0
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val
            loaded += 1
    return loaded


def load(path: str | Path = DEFAULT_PATH) -> dict:
    """Load config.toml merged over defaults; .env + env vars override secrets."""
    load_dotenv()  # populate os.environ from .env first (if present)
    cfg = dict(DEFAULTS)
    p = Path(path)
    if p.exists():
        with open(p, "rb") as f:
            cfg = _merge(DEFAULTS, tomllib.load(f))
    # env overrides for secrets (don't hardcode tokens)
    cfg["apify"]["token"] = os.getenv("APIFY_TOKEN", cfg["apify"]["token"])
    tg = cfg["telegram"]
    tg["bot_token"] = os.getenv("TELEGRAM_BOT_TOKEN", tg["bot_token"])
    tg["chat_id"] = os.getenv("TELEGRAM_CHAT_ID", tg["chat_id"])
    tg["api_hash"] = os.getenv("TELEGRAM_API_HASH", tg["api_hash"])
    if os.getenv("TELEGRAM_API_ID"):
        tg["api_id"] = int(os.getenv("TELEGRAM_API_ID"))
    return cfg
