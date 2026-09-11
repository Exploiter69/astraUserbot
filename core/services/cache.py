"""Bounded three-tier cache: memory, SQLite metadata/value storage, and artifacts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from core.errors import ResourceError

logger = logging.getLogger("astra.services.cache")


@dataclass(slots=True, frozen=True)
class CacheStats:
    hits: int
    misses: int
    l1_entries: int
    l1_bytes: int
    l2_entries: int
    l2_bytes: int
    artifact_entries: int
    artifact_bytes: int


@dataclass(slots=True, frozen=True)
class CacheEntry:
    namespace: str
    key: str
    version: str
    value: Any
    source: str
    content_type: str
    expires_at: float | None


@dataclass(slots=True, frozen=True)
class Artifact:
    namespace: str
    key: str
    path: Path
    size: int
    content_type: str
    expires_at: float | None


@dataclass(slots=True)
class _MemoryItem:
    payload: bytes
    expires_at: float | None
    source: str
    content_type: str


class CacheService:
    """One cache API with bounded L1, persistent L2, and filesystem L3.

    Values are JSON-serialized deliberately: arbitrary object/pickle deserialization
    is not part of the cache trust boundary. Binary data belongs in ``put_artifact``.
    """

    def __init__(
        self,
        project_root: str | Path,
        *,
        cache_dir: str | Path | None = None,
        max_l1_entries: int = 512,
        max_l1_bytes: int = 16 * 1024 * 1024,
        max_l2_entries: int = 10_000,
        max_l2_bytes: int = 128 * 1024 * 1024,
        max_artifact_entries: int = 2_000,
        max_artifact_bytes: int = 512 * 1024 * 1024,
        max_value_bytes: int = 2 * 1024 * 1024,
        max_artifact_bytes_per_item: int = 512 * 1024 * 1024,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.root = (self.project_root / "data" / "cache").resolve() if cache_dir is None else Path(cache_dir).resolve()
        self.db_path = self.root / "cache.sqlite3"
        self.artifact_root = self.root / "artifacts"
        limits = {
            "max_l1_entries": max_l1_entries,
            "max_l1_bytes": max_l1_bytes,
            "max_l2_entries": max_l2_entries,
            "max_l2_bytes": max_l2_bytes,
            "max_artifact_entries": max_artifact_entries,
            "max_artifact_bytes": max_artifact_bytes,
            "max_value_bytes": max_value_bytes,
            "max_artifact_bytes_per_item": max_artifact_bytes_per_item,
        }
        if any(int(value) <= 0 for value in limits.values()):
            raise ValueError("Cache limits must be positive")
        self.max_l1_entries = int(max_l1_entries)
        self.max_l1_bytes = int(max_l1_bytes)
        self.max_l2_entries = int(max_l2_entries)
        self.max_l2_bytes = int(max_l2_bytes)
        self.max_artifact_entries = int(max_artifact_entries)
        self.max_artifact_bytes = int(max_artifact_bytes)
        self.max_value_bytes = int(max_value_bytes)
        self.max_artifact_bytes_per_item = int(max_artifact_bytes_per_item)
        self._l1: OrderedDict[tuple[str, str, str], _MemoryItem] = OrderedDict()
        self._l1_bytes = 0
        self._db: sqlite3.Connection | None = None
        self._db_lock = asyncio.Lock()
        self._key_locks: dict[tuple[str, str, str], asyncio.Lock] = {}
        self._key_locks_guard = asyncio.Lock()
        self._stats = {"hits": 0, "misses": 0}
        self._closed = False

    async def start(self) -> None:
        if self._db is not None:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        async with self._db_lock:
            if self._db is not None:
                return
            db = sqlite3.connect(self.db_path, timeout=10.0)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=10000")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    version TEXT NOT NULL,
                    value BLOB NOT NULL,
                    source TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    accessed_at REAL NOT NULL,
                    expires_at REAL,
                    PRIMARY KEY (namespace, cache_key, version)
                );
                CREATE INDEX IF NOT EXISTS idx_cache_expiry ON cache_entries(expires_at);
                CREATE INDEX IF NOT EXISTS idx_cache_access ON cache_entries(accessed_at);
                CREATE TABLE IF NOT EXISTS cache_artifacts (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    version TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    accessed_at REAL NOT NULL,
                    expires_at REAL,
                    PRIMARY KEY (namespace, cache_key, version)
                );
                CREATE INDEX IF NOT EXISTS idx_artifact_expiry ON cache_artifacts(expires_at);
                CREATE INDEX IF NOT EXISTS idx_artifact_access ON cache_artifacts(accessed_at);
                """
            )
            db.commit()
            self._db = db
            self._closed = False
        await self.cleanup()

    async def close(self) -> None:
        async with self._db_lock:
            if self._db is not None:
                self._db.commit()
                self._db.close()
                self._db = None
        self._l1.clear()
        self._l1_bytes = 0
        self._key_locks.clear()
        self._closed = True

    def _validate_identity(self, namespace: str, key: str, version: str) -> tuple[str, str, str]:
        values = (namespace, key, version)
        if any(not isinstance(value, str) or not value or len(value) > 256 for value in values):
            raise ValueError("Cache namespace, key, and version must be non-empty strings of <= 256 characters")
        return values

    def _expiry(self, ttl: float | None) -> float | None:
        if ttl is None:
            return None
        ttl = float(ttl)
        if ttl <= 0:
            return time.time() - 1
        return time.time() + ttl

    def _expired(self, expires_at: float | None, now: float | None = None) -> bool:
        return expires_at is not None and expires_at <= (time.time() if now is None else now)

    async def _key_lock(self, identity: tuple[str, str, str]) -> asyncio.Lock:
        async with self._key_locks_guard:
            lock = self._key_locks.get(identity)
            if lock is None:
                lock = asyncio.Lock()
                self._key_locks[identity] = lock
            return lock

    async def get(self, namespace: str, key: str, *, version: str = "1") -> CacheEntry | None:
        identity = self._validate_identity(namespace, key, version)
        await self.start()
        item = self._l1.get(identity)
        if item is not None:
            if not self._expired(item.expires_at):
                self._l1.move_to_end(identity)
                self._stats["hits"] += 1
                return CacheEntry(namespace, key, version, json.loads(item.payload), item.source, item.content_type, item.expires_at)
            self._remove_l1(identity)

        row = await self._fetch_l2(identity)
        if row is None:
            self._stats["misses"] += 1
            return None
        expires_at = row["expires_at"]
        if self._expired(expires_at):
            await self.delete(namespace, key, version=version)
            self._stats["misses"] += 1
            return None
        payload = bytes(row["value"])
        self._put_l1(identity, _MemoryItem(payload, expires_at, row["source"], row["content_type"]))
        await self._touch_l2(identity)
        self._stats["hits"] += 1
        return CacheEntry(namespace, key, version, json.loads(payload), row["source"], row["content_type"], expires_at)

    async def set(
        self,
        namespace: str,
        key: str,
        value: Any,
        *,
        version: str = "1",
        ttl: float | None = None,
        source: str = "unknown",
        content_type: str = "application/json",
    ) -> None:
        identity = self._validate_identity(namespace, key, version)
        if not isinstance(source, str) or len(source) > 256:
            raise ValueError("Cache source is invalid")
        if not isinstance(content_type, str) or len(content_type) > 256:
            raise ValueError("Cache content_type is invalid")
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > self.max_value_bytes:
            raise ResourceError("Cache value exceeds the configured size limit.")
        expires_at = self._expiry(ttl)
        await self.start()
        if expires_at is not None and expires_at <= time.time():
            await self.delete(namespace, key, version=version)
            return
        now = time.time()
        async with self._db_lock:
            db = self._require_db()
            db.execute(
                """INSERT INTO cache_entries(namespace, cache_key, version, value, source, content_type,
                   size_bytes, created_at, accessed_at, expires_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(namespace, cache_key, version) DO UPDATE SET
                   value=excluded.value, source=excluded.source, content_type=excluded.content_type,
                   size_bytes=excluded.size_bytes, created_at=excluded.created_at,
                   accessed_at=excluded.accessed_at, expires_at=excluded.expires_at""",
                (namespace, key, version, payload, source, content_type, len(payload), now, now, expires_at),
            )
            db.commit()
            self._evict_l2_locked(now)
        self._put_l1(identity, _MemoryItem(payload, expires_at, source, content_type))

    async def get_or_set(
        self,
        namespace: str,
        key: str,
        factory: Callable[[], Any | Awaitable[Any]],
        *,
        version: str = "1",
        ttl: float | None = None,
        source: str = "unknown",
        content_type: str = "application/json",
    ) -> CacheEntry:
        existing = await self.get(namespace, key, version=version)
        if existing is not None:
            return existing
        lock = await self._key_lock(self._validate_identity(namespace, key, version))
        async with lock:
            existing = await self.get(namespace, key, version=version)
            if existing is not None:
                return existing
            value = factory()
            if asyncio.iscoroutine(value) or isinstance(value, Awaitable):
                value = await value
            await self.set(namespace, key, value, version=version, ttl=ttl, source=source, content_type=content_type)
            created = await self.get(namespace, key, version=version)
            if created is None:
                raise ResourceError("Cache value could not be persisted.")
            return created

    async def delete(self, namespace: str, key: str, *, version: str = "1") -> bool:
        identity = self._validate_identity(namespace, key, version)
        await self.start()
        removed = self._remove_l1(identity)
        async with self._db_lock:
            db = self._require_db()
            cursor = db.execute("DELETE FROM cache_entries WHERE namespace=? AND cache_key=? AND version=?", identity)
            db.commit()
            return removed or cursor.rowcount > 0

    async def invalidate_namespace(self, namespace: str) -> int:
        if not namespace or len(namespace) > 256:
            raise ValueError("Invalid cache namespace")
        await self.start()
        for identity in list(self._l1):
            if identity[0] == namespace:
                self._remove_l1(identity)
        async with self._db_lock:
            db = self._require_db()
            cursor = db.execute("DELETE FROM cache_entries WHERE namespace=?", (namespace,))
            db.commit()
            return max(0, cursor.rowcount)

    async def put_artifact(
        self,
        namespace: str,
        key: str,
        data: bytes,
        *,
        version: str = "1",
        ttl: float | None = None,
        content_type: str = "application/octet-stream",
    ) -> Artifact:
        identity = self._validate_identity(namespace, key, version)
        if len(data) > self.max_artifact_bytes_per_item:
            raise ResourceError("Cache artifact exceeds the configured size limit.")
        expires_at = self._expiry(ttl)
        if expires_at is not None and expires_at <= time.time():
            await self.delete_artifact(namespace, key, version=version)
            raise ResourceError("Cache artifact TTL must be positive.")
        await self.start()
        digest = hashlib.sha256("\0".join(identity).encode()).hexdigest()
        relative = Path("artifacts") / digest[:2] / f"{digest}.bin"
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".cache-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        now = time.time()
        async with self._db_lock:
            db = self._require_db()
            db.execute(
                """INSERT INTO cache_artifacts(namespace, cache_key, version, relative_path, size_bytes,
                   content_type, created_at, accessed_at, expires_at) VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(namespace, cache_key, version) DO UPDATE SET
                   relative_path=excluded.relative_path, size_bytes=excluded.size_bytes,
                   content_type=excluded.content_type, created_at=excluded.created_at,
                   accessed_at=excluded.accessed_at, expires_at=excluded.expires_at""",
                (namespace, key, version, str(relative), len(data), content_type, now, now, expires_at),
            )
            db.commit()
            self._evict_artifacts_locked(now)
        return Artifact(namespace, key, target, len(data), content_type, expires_at)

    async def get_artifact(self, namespace: str, key: str, *, version: str = "1") -> Artifact | None:
        identity = self._validate_identity(namespace, key, version)
        await self.start()
        async with self._db_lock:
            db = self._require_db()
            row = db.execute("SELECT * FROM cache_artifacts WHERE namespace=? AND cache_key=? AND version=?", identity).fetchone()
            if row is None:
                return None
            if self._expired(row["expires_at"]):
                db.execute("DELETE FROM cache_artifacts WHERE namespace=? AND cache_key=? AND version=?", identity)
                db.commit()
                self._unlink_relative(row["relative_path"])
                return None
            path = (self.root / row["relative_path"]).resolve()
            try:
                path.relative_to(self.artifact_root)
            except ValueError:
                db.execute("DELETE FROM cache_artifacts WHERE namespace=? AND cache_key=? AND version=?", identity)
                db.commit()
                return None
            if not path.is_file():
                db.execute("DELETE FROM cache_artifacts WHERE namespace=? AND cache_key=? AND version=?", identity)
                db.commit()
                return None
            db.execute("UPDATE cache_artifacts SET accessed_at=? WHERE namespace=? AND cache_key=? AND version=?", (time.time(), *identity))
            db.commit()
            return Artifact(namespace, key, path, row["size_bytes"], row["content_type"], row["expires_at"])

    async def read_artifact(self, namespace: str, key: str, *, version: str = "1") -> bytes | None:
        artifact = await self.get_artifact(namespace, key, version=version)
        if artifact is None:
            self._stats["misses"] += 1
            return None
        data = await asyncio.to_thread(artifact.path.read_bytes)
        self._stats["hits"] += 1
        return data

    async def delete_artifact(self, namespace: str, key: str, *, version: str = "1") -> bool:
        identity = self._validate_identity(namespace, key, version)
        await self.start()
        async with self._db_lock:
            db = self._require_db()
            row = db.execute("SELECT relative_path FROM cache_artifacts WHERE namespace=? AND cache_key=? AND version=?", identity).fetchone()
            if row is None:
                return False
            db.execute("DELETE FROM cache_artifacts WHERE namespace=? AND cache_key=? AND version=?", identity)
            db.commit()
            self._unlink_relative(row["relative_path"])
            return True

    async def clear(self) -> None:
        await self.start()
        self._l1.clear()
        self._l1_bytes = 0
        async with self._db_lock:
            db = self._require_db()
            rows = db.execute("SELECT relative_path FROM cache_artifacts").fetchall()
            db.execute("DELETE FROM cache_entries")
            db.execute("DELETE FROM cache_artifacts")
            db.commit()
            for row in rows:
                self._unlink_relative(row["relative_path"])

    async def cleanup(self) -> None:
        await self.start() if self._db is None else None
        now = time.time()
        async with self._db_lock:
            db = self._require_db()
            rows = db.execute("SELECT relative_path FROM cache_artifacts WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,)).fetchall()
            db.execute("DELETE FROM cache_entries WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
            db.execute("DELETE FROM cache_artifacts WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
            self._evict_l2_locked(now)
            self._evict_artifacts_locked(now)
            db.commit()
            for row in rows:
                self._unlink_relative(row["relative_path"])
        for identity, item in list(self._l1.items()):
            if self._expired(item.expires_at, now):
                self._remove_l1(identity)

    async def stats(self) -> CacheStats:
        await self.start()
        async with self._db_lock:
            db = self._require_db()
            l2 = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes),0) AS b FROM cache_entries").fetchone()
            artifacts = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes),0) AS b FROM cache_artifacts").fetchone()
        return CacheStats(self._stats["hits"], self._stats["misses"], len(self._l1), self._l1_bytes, l2["n"], l2["b"], artifacts["n"], artifacts["b"])

    def _require_db(self) -> sqlite3.Connection:
        if self._db is None:
            raise RuntimeError("CacheService is not started")
        return self._db

    async def _fetch_l2(self, identity: tuple[str, str, str]) -> sqlite3.Row | None:
        async with self._db_lock:
            return self._require_db().execute("SELECT * FROM cache_entries WHERE namespace=? AND cache_key=? AND version=?", identity).fetchone()

    async def _touch_l2(self, identity: tuple[str, str, str]) -> None:
        async with self._db_lock:
            db = self._require_db()
            db.execute("UPDATE cache_entries SET accessed_at=? WHERE namespace=? AND cache_key=? AND version=?", (time.time(), *identity))
            db.commit()

    def _put_l1(self, identity: tuple[str, str, str], item: _MemoryItem) -> None:
        self._remove_l1(identity)
        self._l1[identity] = item
        self._l1_bytes += len(item.payload)
        while len(self._l1) > self.max_l1_entries or self._l1_bytes > self.max_l1_bytes:
            old_identity, _ = self._l1.popitem(last=False)
            # Re-read the item size is impossible after pop, so keep accounting from the popped value.
            # The branch above intentionally uses the value before removal.
            # This fallback is replaced immediately below by recomputing the bounded total.
            self._l1_bytes = sum(len(entry.payload) for entry in self._l1.values())
            if old_identity == identity and identity not in self._l1:
                break

    def _remove_l1(self, identity: tuple[str, str, str]) -> bool:
        item = self._l1.pop(identity, None)
        if item is None:
            return False
        self._l1_bytes -= len(item.payload)
        return True

    def _evict_l2_locked(self, now: float) -> None:
        db = self._require_db()
        db.execute("DELETE FROM cache_entries WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
        row = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes),0) AS b FROM cache_entries").fetchone()
        while row["n"] > self.max_l2_entries or row["b"] > self.max_l2_bytes:
            victim = db.execute("SELECT namespace, cache_key, version FROM cache_entries ORDER BY accessed_at ASC LIMIT 1").fetchone()
            if victim is None:
                break
            db.execute("DELETE FROM cache_entries WHERE namespace=? AND cache_key=? AND version=?", tuple(victim))
            row = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes),0) AS b FROM cache_entries").fetchone()

    def _evict_artifacts_locked(self, now: float) -> None:
        db = self._require_db()
        expired = db.execute("SELECT relative_path FROM cache_artifacts WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,)).fetchall()
        for row in expired:
            self._unlink_relative(row["relative_path"])
        db.execute("DELETE FROM cache_artifacts WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
        row = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes),0) AS b FROM cache_artifacts").fetchone()
        while row["n"] > self.max_artifact_entries or row["b"] > self.max_artifact_bytes:
            victim = db.execute("SELECT namespace, cache_key, version, relative_path FROM cache_artifacts ORDER BY accessed_at ASC LIMIT 1").fetchone()
            if victim is None:
                break
            self._unlink_relative(victim["relative_path"])
            db.execute("DELETE FROM cache_artifacts WHERE namespace=? AND cache_key=? AND version=?", (victim["namespace"], victim["cache_key"], victim["version"]))
            row = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes),0) AS b FROM cache_artifacts").fetchone()

    def _unlink_relative(self, relative: str) -> None:
        path = (self.root / relative).resolve()
        try:
            path.relative_to(self.artifact_root)
        except ValueError:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to remove cache artifact path=%s", path, exc_info=True)
