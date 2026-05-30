"""CLI orchestrator: collect -> verify -> score -> notify, plus utilities.

Commands:
  run [--source NAME]   full pipeline (or a single source)
  verify --url URL      verify one site, print findings
  export [--out FILE]   CSV of verified services with API + referral
  top [--limit N]       highest-scoring services
  status                DB statistics
Cron-friendly: exit 0 on success, non-zero on error.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys

from . import config as _config
from .db import DB
from .collectors import (hackernews, linux_forums, apify_sources,
                         ai_directories, github_trending, telegram_channels,
                         hidden_gems, foss_sources, forums, asian_dev, launch,
                         reddit_rss, intl_forums)
from . import verifier, scorer, notifier

log = logging.getLogger("ai_finder")

# Canonical collector names (also the valid values for `run --source`).
SOURCE_NAMES = [
    "hackernews", "linux_forums", "apify", "ai_directories", "github_trending",
    "hidden_gems", "foss", "forums", "asian_dev", "launch", "reddit", "telegram",
    "intl_forums",
]

EXPORT_COLS = ["domain", "name", "category", "score", "has_api",
               "api_docs_url", "has_referral", "referral_url",
               "referral_commission", "pricing_model", "source_url",
               "platforms", "description"]


def _source_registry(db: DB, cfg: dict) -> dict:
    """Map source name -> zero-arg coroutine factory for enabled sources."""
    lim = cfg["limits"]
    tg = cfg["telegram"]
    return {
        "hackernews": lambda: hackernews.collect(db, lim.get("hackernews", 100)),
        "linux_forums": lambda: linux_forums.collect(db),
        "apify": lambda: apify_sources.collect(db, cfg["apify"]["token"]),
        "ai_directories": lambda: ai_directories.collect(db),
        "github_trending": lambda: github_trending.collect(
            db, lim.get("github_trending", 25)),
        "hidden_gems": lambda: hidden_gems.collect(db),
        "foss": lambda: foss_sources.collect(db),
        "forums": lambda: forums.collect(db),
        "asian_dev": lambda: asian_dev.collect(db),
        "launch": lambda: launch.collect(db),
        "reddit": lambda: reddit_rss.collect(db),
        "intl_forums": lambda: intl_forums.collect(db),
        "telegram": lambda: telegram_channels.collect(
            db, tg["api_id"], tg["api_hash"], tg["channels"]),
    }


async def _collect(db: DB, cfg: dict, only: str | None) -> int:
    """Run enabled collectors concurrently. Logs per-source failures."""
    src = cfg["sources"]
    registry = _source_registry(db, cfg)
    names = [n for n, factory in registry.items()
             if src.get(n) and only in (None, n)]
    results = await asyncio.gather(
        *[registry[n]() for n in names], return_exceptions=True)
    total = 0
    for name, res in zip(names, results):
        if isinstance(res, Exception):
            log.error("collector %s failed: %s", name, res)
        else:
            total += res
            log.info("collector %s: %d new", name, res)
    return total


async def _verify_pending(db: DB, concurrency: int = 6) -> int:
    """Verify all pending services reusing one browser (fast path)."""
    pending = db.by_status("pending")
    if not pending:
        return 0
    return await verifier.verify_services_batch(
        db, [r["id"] for r in pending], concurrency=concurrency)


async def cmd_run(db: DB, cfg: dict, only: str | None) -> None:
    new = await _collect(db, cfg, only)
    print(f"Collected: {new} new candidates")
    checked = await _verify_pending(db)
    print(f"Verified:  {checked} sites")
    scorer.rescore_all(db)
    tg = cfg["telegram"]
    sent = await notifier.notify_new(
        db, tg["bot_token"], tg["chat_id"], cfg["notify"]["threshold"])
    if sent:
        print(f"Notified:  {sent} services")
    print("Stats:", db.stats())


async def cmd_verify(url: str) -> None:
    f = await verifier.verify(url)
    if not f:
        print("unreachable / no HTML"); return
    for k in ("name", "has_api", "api_docs_url", "has_referral",
              "referral_url", "referral_commission", "pricing_model"):
        print(f"  {k:<20} {f.get(k)}")


def cmd_export(db: DB, out: str, min_score: int = 0,
               require_referral: bool = True) -> None:
    """Export services to CSV.

    Default: those with API *and* referral. `--all` drops the referral
    requirement; `--min-score` filters by score.
    """
    def keep(r) -> bool:
        if r["score"] < min_score:
            return False
        if require_referral:
            return bool(r["has_api"] and r["has_referral"])
        return bool(r["has_api"])

    rows = [r for r in db.all_services() if keep(r)]
    rows.sort(key=lambda r: r["score"], reverse=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=EXPORT_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in EXPORT_COLS})
    print(f"Exported {len(rows)} services to {out}")


def cmd_top(db: DB, limit: int, as_json: bool = False) -> None:
    rows = db.top(limit)
    if as_json:
        cols = ["domain", "name", "category", "score", "has_api",
                "has_referral", "referral_commission", "api_docs_url",
                "referral_url"]
        print(json.dumps([{c: r[c] for c in cols} for r in rows],
                         ensure_ascii=False, indent=2))
        return
    for r in rows:
        print(f"  [{r['score']:>3}] {r['category'] or '-':<11} "
              f"{r['domain']:<30} api={r['has_api']} ref={r['has_referral']}")


def cmd_status(db: DB, as_json: bool = False) -> None:
    s = db.stats()
    if as_json:
        print(json.dumps(s, indent=2))
        return
    print(f"total={s['total']} verified={s['verified']} "
          f"with_api={s['with_api']} with_referral={s['with_referral']}")


def cmd_sources(cfg: dict) -> None:
    src = cfg["sources"]
    for name in SOURCE_NAMES:
        state = "on " if src.get(name) else "off"
        print(f"  [{state}] {name}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ai-finder")
    ap.add_argument("--config", default=str(_config.DEFAULT_PATH))
    ap.add_argument("--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--source", default=None, choices=SOURCE_NAMES,
                       metavar="NAME", help="one of: " + ", ".join(SOURCE_NAMES))
    p_ver = sub.add_parser("verify"); p_ver.add_argument("--url", required=True)
    p_exp = sub.add_parser("export")
    p_exp.add_argument("--out", default="ai_services.csv")
    p_exp.add_argument("--min-score", type=int, default=0)
    p_exp.add_argument("--all", action="store_true",
                       help="include API-only services (drop referral requirement)")
    p_top = sub.add_parser("top")
    p_top.add_argument("--limit", type=int, default=20)
    p_top.add_argument("--json", action="store_true")
    p_status = sub.add_parser("status")
    p_status.add_argument("--json", action="store_true")
    sub.add_parser("sources")
    args = ap.parse_args(argv)

    if args.verbose:
        from .net import setup_logging
        setup_logging(verbose=True)
    else:
        from .net import setup_logging
        setup_logging(verbose=False)

    cfg = _config.load(args.config)
    try:
        if args.cmd == "verify":
            asyncio.run(cmd_verify(args.url))
            return 0
        if args.cmd == "sources":
            cmd_sources(cfg)
            return 0
        db = DB(cfg["db_path"])
        try:
            if args.cmd == "run":
                asyncio.run(cmd_run(db, cfg, args.source))
            elif args.cmd == "export":
                cmd_export(db, args.out, min_score=args.min_score,
                           require_referral=not args.all)
            elif args.cmd == "top":
                cmd_top(db, args.limit, as_json=args.json)
            elif args.cmd == "status":
                cmd_status(db, as_json=args.json)
        finally:
            db.close()
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted — progress saved.", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
