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
import sys

from . import config as _config
from .db import DB
from .collectors import (hackernews, linux_forums, apify_sources,
                         ai_directories, github_trending, telegram_channels,
                         hidden_gems, foss_sources, forums, asian_dev, launch,
                         reddit_rss)
from . import verifier, scorer, notifier

EXPORT_COLS = ["domain", "name", "category", "score", "has_api",
               "api_docs_url", "has_referral", "referral_url",
               "referral_commission", "pricing_model", "source_url",
               "platforms", "description"]


async def _collect(db: DB, cfg: dict, only: str | None) -> int:
    src = cfg["sources"]
    lim = cfg["limits"]
    tasks = []
    if (only in (None, "hackernews")) and src.get("hackernews"):
        tasks.append(hackernews.collect(db, lim.get("hackernews", 100)))
    if (only in (None, "linux_forums")) and src.get("linux_forums"):
        tasks.append(linux_forums.collect(db))
    if (only in (None, "apify")) and src.get("apify"):
        tasks.append(apify_sources.collect(db, cfg["apify"]["token"]))
    if (only in (None, "ai_directories")) and src.get("ai_directories"):
        tasks.append(ai_directories.collect(db))
    if (only in (None, "github_trending")) and src.get("github_trending"):
        tasks.append(github_trending.collect(db, lim.get("github_trending", 25)))
    if (only in (None, "hidden_gems")) and src.get("hidden_gems"):
        tasks.append(hidden_gems.collect(db))
    if (only in (None, "foss")) and src.get("foss"):
        tasks.append(foss_sources.collect(db))
    if (only in (None, "forums")) and src.get("forums"):
        tasks.append(forums.collect(db))
    if (only in (None, "asian_dev")) and src.get("asian_dev"):
        tasks.append(asian_dev.collect(db))
    if (only in (None, "launch")) and src.get("launch"):
        tasks.append(launch.collect(db))
    if (only in (None, "reddit")) and src.get("reddit"):
        tasks.append(reddit_rss.collect(db))
    if (only in (None, "telegram")) and src.get("telegram"):
        tg = cfg["telegram"]
        tasks.append(telegram_channels.collect(
            db, tg["api_id"], tg["api_hash"], tg["channels"]))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return sum(r for r in results if isinstance(r, int))


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


def cmd_export(db: DB, out: str) -> None:
    rows = [r for r in db.all_services() if r["has_api"] and r["has_referral"]]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=EXPORT_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in EXPORT_COLS})
    print(f"Exported {len(rows)} services to {out}")


def cmd_top(db: DB, limit: int) -> None:
    for r in db.top(limit):
        print(f"  [{r['score']:>3}] {r['category'] or '-':<11} "
              f"{r['domain']:<30} api={r['has_api']} ref={r['has_referral']}")


def cmd_status(db: DB) -> None:
    s = db.stats()
    print(f"total={s['total']} verified={s['verified']} "
          f"with_api={s['with_api']} with_referral={s['with_referral']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ai-finder")
    ap.add_argument("--config", default=str(_config.DEFAULT_PATH))
    ap.add_argument("--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run"); p_run.add_argument("--source", default=None)
    p_ver = sub.add_parser("verify"); p_ver.add_argument("--url", required=True)
    p_exp = sub.add_parser("export"); p_exp.add_argument("--out", default="ai_services.csv")
    p_top = sub.add_parser("top"); p_top.add_argument("--limit", type=int, default=20)
    sub.add_parser("status")
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
        db = DB(cfg["db_path"])
        try:
            if args.cmd == "run":
                asyncio.run(cmd_run(db, cfg, args.source))
            elif args.cmd == "export":
                cmd_export(db, args.out)
            elif args.cmd == "top":
                cmd_top(db, args.limit)
            elif args.cmd == "status":
                cmd_status(db)
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
