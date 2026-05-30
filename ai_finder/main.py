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
from . import notifier, scorer, tracker, verifier
from .collectors import (
    ai_directories,
    apify_sources,
    asian_dev,
    forums,
    foss_sources,
    github_trending,
    hackernews,
    hidden_gems,
    intl_forums,
    launch,
    linux_forums,
    mastodon,
    reddit_rss,
    telegram_channels,
)
from .db import DB

log = logging.getLogger("ai_finder")

# Canonical collector names (also the valid values for `run --source`).
SOURCE_NAMES = [
    "hackernews", "linux_forums", "apify", "ai_directories", "github_trending",
    "hidden_gems", "foss", "forums", "asian_dev", "launch", "reddit", "telegram",
    "intl_forums", "mastodon",
]

EXPORT_COLS = ["domain", "name", "category", "score", "has_api",
               "api_docs_url", "has_referral", "referral_url",
               "referral_commission", "affiliate_platform", "pricing_model",
               "source_url", "platforms", "description"]


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
        "mastodon": lambda: mastodon.collect(db),
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


async def _verify_pending(db: DB, concurrency: int = 6,
                          retry_cooldown_h: float = 24.0) -> int:
    """Verify pending services + retry unreachable ones past the cooldown.

    Transient failures (timeouts, blips) shouldn't strand a service forever, so
    `unreachable` entries older than `retry_cooldown_h` hours get another shot.
    """
    due = list(db.by_status("pending"))
    if retry_cooldown_h > 0:
        due += db.stale_unreachable(retry_cooldown_h * 3600)
    if not due:
        return 0
    ids = [r["id"] for r in due]
    return await verifier.verify_services_batch(db, ids, concurrency=concurrency)


async def cmd_run(db: DB, cfg: dict, only: str | None) -> None:
    new = await _collect(db, cfg, only)
    print(f"Collected: {new} new candidates")
    vcfg = cfg.get("verify", {})
    checked = await _verify_pending(
        db,
        concurrency=int(vcfg.get("concurrency", 6)),
        retry_cooldown_h=float(vcfg.get("retry_cooldown_h", 24.0)),
    )
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
        print("unreachable / no HTML")
        return
    for k in ("name", "has_api", "api_docs_url", "has_referral",
              "referral_url", "referral_commission", "pricing_model"):
        print(f"  {k:<20} {f.get(k)}")


def _rows_to_dicts(rows):
    return [{k: r[k] for k in EXPORT_COLS} for r in rows]


def _to_markdown(rows) -> str:
    cols = ["domain", "name", "category", "score", "has_api",
            "has_referral", "referral_commission", "referral_url", "api_docs_url"]
    out = ["| " + " | ".join(cols) + " |",
           "|" + "|".join("---" for _ in cols) + "|"]
    for r in rows:
        cells = [str(r[c] if r[c] is not None else "").replace("|", "\\|")
                 for c in cols]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def cmd_export(db: DB, out: str, min_score: int = 0,
               require_referral: bool = True, fmt: str = "csv") -> None:
    """Export services to CSV/JSON/Markdown.

    Default: those with API *and* referral. `--all` drops the referral
    requirement; `--min-score` filters by score; `--format` picks the writer.
    """
    def keep(r) -> bool:
        if r["score"] < min_score:
            return False
        if require_referral:
            return bool(r["has_api"] and r["has_referral"])
        return bool(r["has_api"])

    rows = [r for r in db.all_services() if keep(r)]
    rows.sort(key=lambda r: r["score"], reverse=True)
    if fmt == "json":
        with open(out, "w") as f:
            json.dump(_rows_to_dicts(rows), f, ensure_ascii=False, indent=2)
    elif fmt == "md":
        with open(out, "w") as f:
            f.write(_to_markdown(rows))
    else:  # csv
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


def cmd_prune(db: DB, status: str) -> None:
    n = db.delete_services(status)
    print(f"Pruned {n} services with status '{status}'")


def cmd_report(db: DB, as_json: bool = False) -> None:
    """Per-source collector stats from sources_log."""
    rows = db.source_report()
    if as_json:
        cols = ["source", "runs", "candidates", "new_services", "last_run"]
        print(json.dumps([{c: r[c] for c in cols} for r in rows], indent=2))
        return
    if not rows:
        print("No collector runs logged yet.")
        return
    from datetime import datetime, timezone
    print(f"{'source':<16} {'runs':>5} {'cand':>7} {'new':>6}  last_run")
    for r in rows:
        last = datetime.fromtimestamp(r["last_run"], timezone.utc).strftime(
            "%Y-%m-%d %H:%M") if r["last_run"] else "-"
        print(f"{r['source']:<16} {r['runs']:>5} {r['candidates'] or 0:>7} "
              f"{r['new_services'] or 0:>6}  {last}")


def monetizable_referral_urls(db: DB, limit: int) -> list[str]:
    """Pure-ish: referral URLs of top monetizable finds (dedup, capped)."""
    urls = []
    seen = set()
    for r in db.monetizable(limit * 2):
        u = r["referral_url"]
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
        if len(urls) >= limit:
            break
    return urls


def cmd_open(db: DB, limit: int) -> None:
    """Open top monetizable referral URLs in the default browser."""
    import webbrowser
    urls = monetizable_referral_urls(db, limit)
    if not urls:
        print("No referral URLs to open (run + verify first).")
        return
    for u in urls:
        print(f"opening {u}")
        webbrowser.open(u)


def cmd_links(db: DB, limit: int) -> None:
    """Print copy-friendly referral + API links for monetizable finds."""
    rows = db.monetizable(limit)
    if not rows:
        print("No monetizable services yet (run + verify first).")
        return
    for r in rows:
        name = r["name"] or r["domain"]
        comm = f" ({r['referral_commission']})" if r["referral_commission"] else ""
        plat = r["affiliate_platform"] if "affiliate_platform" in r.keys() else ""
        via = f" via {plat}" if plat else ""
        print(f"[{r['score']:>3}] {name}{comm}{via}")
        if r["referral_url"]:
            print(f"      referral: {r['referral_url']}")
        if r["api_docs_url"]:
            print(f"      api:      {r['api_docs_url']}")


def cmd_history(db: DB, domain: str) -> None:
    from datetime import datetime, timezone

    from .db import domain_of
    rows = db.get_history(domain_of(domain))
    if not rows:
        print(f"No recorded changes for {domain}.")
        return
    for r in rows:
        ts = datetime.fromtimestamp(r["changed_at"], timezone.utc).strftime(
            "%Y-%m-%d %H:%M")
        print(f"  {ts}  {r['field']}: {r['old_value']} -> {r['new_value']}")


async def cmd_digest(db: DB, cfg: dict, limit: int) -> None:
    tg = cfg["telegram"]
    ok = await notifier.send_digest(db, tg["bot_token"], tg["chat_id"], limit)
    print("Digest sent." if ok else
          "Digest not sent (no Telegram token/chat or no services).")


async def cmd_recheck(db: DB, max_age_days: float, only_verified: bool) -> None:
    report = await tracker.recheck_all(
        db, only_verified=only_verified, max_age_days=max_age_days)
    if not report:
        print("No changes detected.")
        return
    for domain, changes in report.items():
        print(f"{domain}:")
        for field, ov, nv in changes:
            print(f"  {field}: {ov} -> {nv}")


def cmd_search(db: DB, keyword: str, category: str, min_score: int,
               limit: int, as_json: bool = False) -> None:
    rows = db.search(keyword=keyword, category=category,
                     min_score=min_score, limit=limit)
    if as_json:
        cols = ["domain", "name", "category", "score", "has_api",
                "has_referral", "referral_commission", "api_docs_url",
                "referral_url"]
        print(json.dumps([{c: r[c] for c in cols} for r in rows],
                         ensure_ascii=False, indent=2))
        return
    if not rows:
        print("No matches.")
        return
    for r in rows:
        print(f"  [{r['score']:>3}] {r['category'] or '-':<11} "
              f"{r['domain']:<30} api={r['has_api']} ref={r['has_referral']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ai-finder")
    ap.add_argument("--config", default=str(_config.DEFAULT_PATH))
    ap.add_argument("--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--source", default=None, choices=SOURCE_NAMES,
                       metavar="NAME", help="one of: " + ", ".join(SOURCE_NAMES))
    p_ver = sub.add_parser("verify")
    p_ver.add_argument("--url", required=True)
    p_exp = sub.add_parser("export")
    p_exp.add_argument("--out", default=None)
    p_exp.add_argument("--format", choices=["csv", "json", "md"], default="csv")
    p_exp.add_argument("--min-score", type=int, default=0)
    p_exp.add_argument("--all", action="store_true",
                       help="include API-only services (drop referral requirement)")
    p_top = sub.add_parser("top")
    p_top.add_argument("--limit", type=int, default=20)
    p_top.add_argument("--json", action="store_true")
    p_status = sub.add_parser("status")
    p_status.add_argument("--json", action="store_true")
    sub.add_parser("sources")
    p_search = sub.add_parser("search")
    p_search.add_argument("--keyword", default="")
    p_search.add_argument("--category", default="")
    p_search.add_argument("--min-score", type=int, default=0)
    p_search.add_argument("--limit", type=int, default=50)
    p_search.add_argument("--json", action="store_true")
    p_prune = sub.add_parser("prune")
    p_prune.add_argument("--status", default="unreachable")
    p_recheck = sub.add_parser("recheck")
    p_recheck.add_argument("--max-age-days", type=float, default=7.0)
    p_recheck.add_argument("--all", action="store_true",
                           help="recheck all services, not just verified/notified")
    p_hist = sub.add_parser("history")
    p_hist.add_argument("--domain", required=True)
    p_digest = sub.add_parser("digest")
    p_digest.add_argument("--limit", type=int, default=10)
    p_links = sub.add_parser("links")
    p_links.add_argument("--limit", type=int, default=25)
    p_open = sub.add_parser("open")
    p_open.add_argument("--limit", type=int, default=5)
    p_report = sub.add_parser("report")
    p_report.add_argument("--json", action="store_true")
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
                out = args.out or f"ai_services.{args.format}"
                cmd_export(db, out, min_score=args.min_score,
                           require_referral=not args.all, fmt=args.format)
            elif args.cmd == "top":
                cmd_top(db, args.limit, as_json=args.json)
            elif args.cmd == "status":
                cmd_status(db, as_json=args.json)
            elif args.cmd == "search":
                cmd_search(db, args.keyword, args.category, args.min_score,
                           args.limit, as_json=args.json)
            elif args.cmd == "prune":
                cmd_prune(db, args.status)
            elif args.cmd == "recheck":
                asyncio.run(cmd_recheck(db, args.max_age_days,
                                        only_verified=not args.all))
            elif args.cmd == "history":
                cmd_history(db, args.domain)
            elif args.cmd == "digest":
                asyncio.run(cmd_digest(db, cfg, args.limit))
            elif args.cmd == "links":
                cmd_links(db, args.limit)
            elif args.cmd == "open":
                cmd_open(db, args.limit)
            elif args.cmd == "report":
                cmd_report(db, as_json=args.json)
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
