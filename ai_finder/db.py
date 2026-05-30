"""SQLite storage: schema, CRUD, dedup by domain."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import tldextract

DEFAULT_DB = Path(__file__).resolve().parent.parent / "ai_finder.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT UNIQUE NOT NULL,
    name TEXT,
    description TEXT,
    source_url TEXT,
    source_platform TEXT,
    has_api INTEGER DEFAULT 0,
    api_docs_url TEXT,
    has_referral INTEGER DEFAULT 0,
    referral_url TEXT,
    referral_commission TEXT,
    affiliate_platform TEXT,
    pricing_info TEXT,
    pricing_model TEXT,
    category TEXT,
    score INTEGER DEFAULT 0,
    upvotes INTEGER DEFAULT 0,
    platforms TEXT DEFAULT '',
    discovered_at REAL,
    verified_at REAL,
    last_checked REAL,
    status TEXT DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS sources_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,
    run_at REAL,
    candidates_found INTEGER,
    new_services INTEGER
);
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER,
    tag TEXT,
    UNIQUE(service_id, tag)
);
CREATE TABLE IF NOT EXISTS service_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER,
    changed_at REAL,
    field TEXT,
    old_value TEXT,
    new_value TEXT
);
CREATE INDEX IF NOT EXISTS idx_services_status ON services(status);
CREATE INDEX IF NOT EXISTS idx_services_score ON services(score DESC);
"""


# Subdomain labels that denote the same service (collapsed for dedup).
_COMMON_SUBDOMAINS = {
    "www", "app", "apps", "docs", "doc", "api", "dev", "developer",
    "developers", "get", "go", "my", "beta", "dashboard", "console",
    "portal", "platform", "try", "start", "home", "web",
}

# Offline extractor backed by the bundled Public Suffix List snapshot.
_TLD = tldextract.TLDExtract(suffix_list_urls=())


def domain_of(url: str) -> str:
    """Normalize a URL to its registrable host using the Public Suffix List,
    with common service subdomains stripped (www/app/docs/api/...).

    - Multi-level suffixes are handled correctly (``foo.com.cn`` →
      ``foo.com.cn``, ``app.foo.com.cn`` → ``foo.com.cn``).
    - Near-duplicates collapse (``app.klingai.com`` → ``klingai.com``).
    - Meaningful subdomains are kept (``jimeng.jianying.com`` stays whole).
    """
    if "://" not in url:
        url = "http://" + url
    ext = _TLD(url)
    registrable = ext.top_domain_under_public_suffix  # e.g. foo.com.cn
    if not registrable:
        # no recognizable public suffix — fall back to the raw host
        from urllib.parse import urlparse
        return (urlparse(url).hostname or "").lower()
    # strip only the *leading* common-service labels from the subdomain part
    sub_labels = [s for s in ext.subdomain.split(".") if s]
    while sub_labels and sub_labels[0] in _COMMON_SUBDOMAINS:
        sub_labels.pop(0)
    host = ".".join(sub_labels + [registrable])
    return host.lower()


# Generic/infra domains that are never the niche AI service we want to track.
NOISE_DOMAINS = {
    "github.com", "gitlab.com", "bitbucket.org", "google.com", "youtube.com",
    "youtu.be", "twitter.com", "x.com", "facebook.com", "linkedin.com",
    "instagram.com", "reddit.com", "wikipedia.org", "medium.com",
    "substack.com", "apple.com", "microsoft.com", "amazon.com",
    "producthunt.com", "news.ycombinator.com",
}

# News/media outlets — they report on AI, they aren't the service itself.
NEWS_DOMAINS = {
    "arstechnica.com", "techcrunch.com", "theverge.com", "wired.com",
    "nytimes.com", "bbc.com", "cnbc.com", "fastcompany.com", "gizmodo.com",
    "theinformation.com", "harvardmagazine.com", "lesswrong.com", "ign.com",
    "store.steampowered.com", "steamcommunity.com", "gadgetreview.com",
    "legiscan.com", "bloomberg.com", "reuters.com", "wsj.com", "forbes.com",
    "businessinsider.com", "engadget.com", "venturebeat.com", "zdnet.com",
    "cnet.com", "axios.com", "aljazeera.com", "theguardian.com", "cnn.com",
    "tomshardware.com", "sfstandard.com", "tiktok.com", "arxiv.org",
    "404media.co", "theregister.com", "thurrott.com", "neowin.net",
    "scientificamerican.com", "boredpanda.com", "nature.com",
    "spectrum.ieee.org", "phys.org", "sciencedaily.com",
}


def is_noise_domain(domain: str) -> bool:
    """True for generic/infra/news hosts that aren't a discoverable service."""
    if not domain:
        return True
    # Non-public hosts: localhost, IPs, systemd targets, no-dot/TLD-less names.
    if domain in ("localhost",) or domain.startswith("127.") or \
            domain.replace(".", "").isdigit() or "." not in domain or \
            domain.endswith((".local", ".target", ".service", ".lan")):
        return True
    return any(domain == n or domain.endswith("." + n)
               for n in NOISE_DOMAINS | NEWS_DOMAINS)


@dataclass
class Candidate:
    """A discovered service candidate before verification."""
    url: str
    name: str = ""
    description: str = ""
    source_platform: str = ""
    upvotes: int = 0
    domain: str = field(default="")

    def __post_init__(self):
        if not self.domain:
            self.domain = domain_of(self.url)


class DB:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """Add columns introduced after a DB was first created (idempotent)."""
        cols = {r["name"] for r in self.conn.execute(
            "PRAGMA table_info(services)")}
        for col in ("affiliate_platform",):
            if col not in cols:
                self.conn.execute(f"ALTER TABLE services ADD COLUMN {col} TEXT")

    def close(self):
        self.conn.close()

    @contextmanager
    def _tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def upsert_candidate(self, c: Candidate) -> tuple[int, bool]:
        """Insert candidate or merge into existing (dedup by domain).

        Returns (service_id, is_new).
        """
        if not c.domain:
            raise ValueError(f"candidate has no domain: {c.url}")
        if is_noise_domain(c.domain):
            return -1, False  # skip generic/infra hosts
        now = time.time()
        with self._tx() as conn:
            row = conn.execute(
                "SELECT id, platforms, upvotes FROM services WHERE domain=?",
                (c.domain,),
            ).fetchone()
            if row is None:
                cur = conn.execute(
                    """INSERT INTO services
                    (domain,name,description,source_url,source_platform,
                     upvotes,platforms,discovered_at,status)
                    VALUES (?,?,?,?,?,?,?,?,'pending')""",
                    (c.domain, c.name, c.description, c.url, c.source_platform,
                     c.upvotes, c.source_platform, now),
                )
                return cur.lastrowid, True
            # merge: track platforms, keep max upvotes, fill missing fields
            platforms = set(filter(None, (row["platforms"] or "").split(",")))
            platforms.add(c.source_platform)
            conn.execute(
                """UPDATE services SET platforms=?, upvotes=MAX(upvotes,?),
                   name=COALESCE(NULLIF(name,''),?),
                   description=COALESCE(NULLIF(description,''),?)
                   WHERE id=?""",
                (",".join(sorted(platforms)), c.upvotes, c.name,
                 c.description, row["id"]),
            )
            return row["id"], False

    def update_service(self, service_id: int, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._tx() as conn:
            conn.execute(
                f"UPDATE services SET {cols} WHERE id=?",
                (*fields.values(), service_id),
            )

    def add_tag(self, service_id: int, tag: str):
        with self._tx() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO tags (service_id, tag) VALUES (?,?)",
                (service_id, tag),
            )

    def log_source(self, source: str, candidates: int, new: int):
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO sources_log (source,run_at,candidates_found,new_services) VALUES (?,?,?,?)",
                (source, time.time(), candidates, new),
            )

    def record_change(self, service_id: int, fieldname: str, old, new):
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO service_history (service_id,changed_at,field,old_value,new_value) VALUES (?,?,?,?,?)",
                (service_id, time.time(), fieldname, str(old), str(new)),
            )

    def get(self, service_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM services WHERE id=?", (service_id,)
        ).fetchone()

    def by_status(self, status: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM services WHERE status=?", (status,)
        ).fetchall()

    def top(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM services ORDER BY score DESC LIMIT ?", (limit,)
        ).fetchall()

    def all_services(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM services").fetchall()

    def source_report(self) -> list[sqlite3.Row]:
        """Per-source aggregate of collector runs from sources_log."""
        return self.conn.execute(
            "SELECT source, COUNT(*) AS runs, "
            "SUM(candidates_found) AS candidates, "
            "SUM(new_services) AS new_services, "
            "MAX(run_at) AS last_run "
            "FROM sources_log GROUP BY source "
            "ORDER BY new_services DESC",
        ).fetchall()

    def monetizable(self, limit: int = 50) -> list[sqlite3.Row]:
        """Services with a referral program, best first — the ones you can
        actually earn from. Ordered by score desc."""
        return self.conn.execute(
            "SELECT * FROM services WHERE has_referral=1 "
            "ORDER BY score DESC LIMIT ?", (limit,),
        ).fetchall()

    def get_history(self, domain: str) -> list[sqlite3.Row]:
        """Return change history for a domain, oldest first."""
        return self.conn.execute(
            "SELECT h.changed_at, h.field, h.old_value, h.new_value "
            "FROM service_history h JOIN services s ON s.id = h.service_id "
            "WHERE s.domain = ? ORDER BY h.changed_at ASC", (domain,),
        ).fetchall()

    def delete_services(self, status: str) -> int:
        """Delete services with the given status (+ their tags/history).
        Returns the number of services removed."""
        with self._tx() as conn:
            ids = [r[0] for r in conn.execute(
                "SELECT id FROM services WHERE status=?", (status,)).fetchall()]
            if not ids:
                return 0
            qmarks = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM tags WHERE service_id IN ({qmarks})", ids)
            conn.execute(
                f"DELETE FROM service_history WHERE service_id IN ({qmarks})", ids)
            conn.execute(f"DELETE FROM services WHERE id IN ({qmarks})", ids)
            return len(ids)

    def search(self, keyword: str = "", category: str = "",
               min_score: int = 0, limit: int = 50) -> list[sqlite3.Row]:
        """Filter services by keyword (domain/name/description), category,
        and minimum score. Ordered by score desc."""
        clauses, params = ["score >= ?"], [min_score]
        if keyword:
            clauses.append("(domain LIKE ? OR name LIKE ? OR description LIKE ?)")
            like = f"%{keyword}%"
            params += [like, like, like]
        if category:
            clauses.append("category = ?")
            params.append(category)
        params.append(limit)
        return self.conn.execute(
            f"SELECT * FROM services WHERE {' AND '.join(clauses)} "
            f"ORDER BY score DESC LIMIT ?", params,
        ).fetchall()

    def stats(self) -> dict:
        c = self.conn
        return {
            "total": c.execute("SELECT COUNT(*) FROM services").fetchone()[0],
            "verified": c.execute(
                "SELECT COUNT(*) FROM services WHERE status='verified'"
            ).fetchone()[0],
            "with_api": c.execute(
                "SELECT COUNT(*) FROM services WHERE has_api=1"
            ).fetchone()[0],
            "with_referral": c.execute(
                "SELECT COUNT(*) FROM services WHERE has_referral=1"
            ).fetchone()[0],
        }


if __name__ == "__main__":
    db = DB()
    print(f"DB created at {db.path}")
    print("Tables:", [r[0] for r in db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")])
    sid, new = db.upsert_candidate(
        Candidate(url="https://geekai.co", name="GeekAI",
                  source_platform="demo"))
    print(f"Inserted service id={sid} new={new}")
    print("Stats:", db.stats())
    db.close()
