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
    },
    "limits": {"hackernews": 100, "github_trending": 25},
    "rate": {"per_domain_delay": 1.0, "max_retries": 3},
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


def load(path: str | Path = DEFAULT_PATH) -> dict:
    """Load config.toml merged over defaults; env vars override secrets."""
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
