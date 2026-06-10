"""Freshness / competitor tracker.

Re-verifies previously discovered services, detects meaningful changes
(referral terms, API availability, going dead), and records them in
service_history. `diff_fields` is pure and unit-tested.
"""

from __future__ import annotations

import asyncio
import time

from .db import DB
from .verifier import verify

# Fields worth tracking for change over time.
TRACKED = ("has_api", "has_referral", "referral_commission", "status")

DAY = 86400.0


def needs_recheck(last_checked, max_age_days: float, now: float | None = None) -> bool:
    """Pure: True if a service is due for re-check (never checked or stale)."""
    if not last_checked:
        return True
    now = time.time() if now is None else now
    return (now - float(last_checked)) >= max_age_days * DAY


def diff_fields(old: dict, new: dict) -> list[tuple[str, str, str]]:
    """Pure: list (field, old, new) for tracked fields that changed."""
    changes = []
    for f in TRACKED:
        ov, nv = old.get(f), new.get(f)
        if f in new and str(ov) != str(nv):
            changes.append((f, str(ov), str(nv)))
    return changes


async def recheck_service(db: DB, service_id: int) -> list[tuple]:
    """Re-verify one service, record + return changes."""
    row = db.get(service_id)
    if not row:
        return []
    old = dict(row)
    findings = await verify(old["source_url"] or old["domain"])
    if not findings:
        new = {"status": "unreachable"}
    else:
        new = {
            "has_api": int(findings["has_api"]),
            "has_referral": int(findings["has_referral"]),
            "referral_commission": findings["referral_commission"],
            "status": "verified",
        }
    changes = diff_fields(old, new)
    for field, ov, nv in changes:
        db.record_change(service_id, field, ov, nv)
    db.update_service(service_id, last_checked=time.time(), **new)
    return changes


async def recheck_all(
    db: DB, only_verified: bool = True, max_age_days: float = 7.0, concurrency: int = 6
) -> dict:
    """Re-verify stored services older than `max_age_days`.

    Returns {domain: changes} for services whose tracked fields changed.
    Recently-checked services are skipped to save time/bandwidth.
    """
    rows = (
        (db.by_status("verified") + db.by_status("notified"))
        if only_verified
        else db.all_services()
    )

    sem = asyncio.Semaphore(concurrency)

    async def _bounded(row):
        async with sem:
            return row["domain"], await recheck_service(db, row["id"])

    # Filter in Python (SQL-side filtering would be better but requires DB refactor)
    due = [r for r in rows if needs_recheck(r["last_checked"], max_age_days)]
    if not due:
        return {}

    results = await asyncio.gather(*[_bounded(r) for r in due], return_exceptions=True)

    report = {}
    for res in results:
        if isinstance(res, Exception):
            continue
        domain, changes = res
        if changes:
            report[domain] = changes
    return report


if __name__ == "__main__":
    db = DB()
    try:
        report = asyncio.run(recheck_all(db))
        if not report:
            print("No changes detected (or no verified services yet).")
        for domain, changes in report.items():
            print(f"{domain}:")
            for field, ov, nv in changes:
                print(f"  {field}: {ov} -> {nv}")
    finally:
        db.close()
