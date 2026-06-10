from __future__ import annotations

import asyncio
import hashlib
import math
import sqlite3
import time


class BloomFilter:
    def __init__(self, capacity: int = 100_000, fp_rate: float = 0.01) -> None:
        if capacity <= 0:
            raise ValueError("capacity>0")
        if not 0 < fp_rate < 1:
            raise ValueError("fp_rate in (0,1)")
        self._m = max(1, math.ceil(-capacity * math.log(fp_rate) / (math.log(2) ** 2)))
        self._k = max(1, round((self._m / capacity) * math.log(2)))
        self._bits = bytearray(math.ceil(self._m / 8))
        self._count = 0

    def _pos(self, item: str) -> list[int]:
        d = item.encode()
        h1 = int.from_bytes(hashlib.sha256(d).digest()[:8], "big") % self._m
        h2 = (int.from_bytes(hashlib.md5(d).digest()[:8], "big") % self._m) or 1  # noqa: S324
        return [(h1 + i * h2) % self._m for i in range(self._k)]

    def add(self, item: str) -> None:
        for p in self._pos(item):
            self._bits[p >> 3] |= 1 << (p & 7)
        self._count += 1

    def contains(self, item: str) -> bool:
        return all(self._bits[p >> 3] & (1 << (p & 7)) for p in self._pos(item))

    def clear(self) -> None:
        for i in range(len(self._bits)):
            self._bits[i] = 0
        self._count = 0

    @property
    def count(self) -> int:
        return self._count

    @property
    def fill_ratio(self) -> float:
        return sum(bin(b).count("1") for b in self._bits) / self._m


class URLDeduplicator:
    _T = "url_fingerprints"

    def __init__(
        self, db_path: str = "ai_finder.db", capacity: int = 200_000, fp_rate: float = 0.005
    ) -> None:
        self._db = db_path
        self._bl = BloomFilter(capacity, fp_rate)
        self._lock: asyncio.Lock | None = None

    def _lk(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _cn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db, timeout=5, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute(
            f"CREATE TABLE IF NOT EXISTS {self._T} (fingerprint TEXT PRIMARY KEY,url TEXT NOT NULL,seen_at REAL NOT NULL)"
        )
        c.commit()
        return c

    def load(self) -> int:
        try:
            c = self._cn()
            rows = c.execute(f"SELECT fingerprint FROM {self._T}").fetchall()
            c.close()
            for (fp,) in rows:
                self._bl.add(fp)
            return len(rows)
        except Exception:
            return 0

    async def is_seen(self, url: str) -> bool:
        from ai_finder.fingerprint import fingerprint_url

        fp = fingerprint_url(url)
        if not self._bl.contains(fp):
            return False
        async with self._lk():
            try:
                c = self._cn()
                r = c.execute(
                    f"SELECT 1 FROM {self._T} WHERE fingerprint=? LIMIT 1", (fp,)
                ).fetchone()
                c.close()
                return r is not None
            except Exception:
                return False

    async def mark_seen(self, url: str) -> None:
        from ai_finder.fingerprint import fingerprint_url

        fp = fingerprint_url(url)
        async with self._lk():
            self._bl.add(fp)
            try:
                c = self._cn()
                c.execute(
                    f"INSERT OR IGNORE INTO {self._T} (fingerprint,url,seen_at) VALUES(?,?,?)",
                    (fp, url, time.time()),
                )
                c.commit()
                c.close()
            except Exception:
                pass

    def stats(self) -> dict:
        return {"bloom_count": self._bl.count, "fill_ratio": round(self._bl.fill_ratio, 4)}
