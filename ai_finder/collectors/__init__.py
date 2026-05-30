"""Source collectors."""
from __future__ import annotations


def store_candidates(db, platform: str, cands) -> int:
    """Upsert candidates, log the source run, return count of new services.

    Shared by every collector's ``collect()`` so the persist/log boilerplate
    lives in one place.
    """
    cands = list(cands)
    new = sum(db.upsert_candidate(c)[1] for c in cands)
    db.log_source(platform, len(cands), new)
    return new
