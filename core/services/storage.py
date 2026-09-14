"""Canonical platform SQLite storage and deterministic migrations."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

import aiosqlite


MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, """
    CREATE TABLE IF NOT EXISTS plugins (name TEXT PRIMARY KEY, module TEXT NOT NULL, state TEXT NOT NULL, updated_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS commands (pattern TEXT PRIMARY KEY, plugin_name TEXT, aliases_json TEXT NOT NULL DEFAULT '[]', metadata_json TEXT NOT NULL DEFAULT '{}', updated_at REAL NOT NULL, FOREIGN KEY(plugin_name) REFERENCES plugins(name) ON DELETE SET NULL);
    CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, type TEXT NOT NULL, state TEXT NOT NULL, payload_json TEXT NOT NULL, result_json TEXT, error_code TEXT, error_message TEXT, owner TEXT, parent_id TEXT, idempotency_key TEXT UNIQUE, resource_class TEXT NOT NULL DEFAULT 'default', priority INTEGER NOT NULL DEFAULT 0, progress REAL NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL, available_at REAL NOT NULL, started_at REAL, completed_at REAL, max_attempts INTEGER NOT NULL DEFAULT 3, attempt_count INTEGER NOT NULL DEFAULT 0, verify_required INTEGER NOT NULL DEFAULT 0, FOREIGN KEY(parent_id) REFERENCES jobs(id) ON DELETE SET NULL);
    CREATE INDEX IF NOT EXISTS idx_jobs_ready ON jobs(state, available_at, priority DESC, created_at);
    CREATE INDEX IF NOT EXISTS idx_jobs_parent ON jobs(parent_id);
    CREATE TABLE IF NOT EXISTS job_attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, attempt INTEGER NOT NULL, state TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL, error_code TEXT, error_message TEXT, FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS job_events (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL, FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS leases (job_id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, leased_at REAL NOT NULL, heartbeat_at REAL NOT NULL, expires_at REAL NOT NULL, FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE);
    CREATE TABLE IF NOT EXISTS audit_events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, subject_id TEXT, payload_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at);
    """),
    (2, """
    CREATE TABLE IF NOT EXISTS feature_flags (name TEXT PRIMARY KEY, enabled INTEGER NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', updated_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS search_documents (id TEXT PRIMARY KEY, source TEXT NOT NULL, ref TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL, updated_at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_search_documents_source ON search_documents(source);
    CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(id UNINDEXED, title, content, tokenize='unicode61');
    """),
    (3, """
    ALTER TABLE leases ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0;
    UPDATE leases SET attempt=(SELECT attempt_count FROM jobs WHERE jobs.id=leases.job_id);
    CREATE INDEX IF NOT EXISTS idx_leases_expiry ON leases(expires_at);
    CREATE INDEX IF NOT EXISTS idx_job_attempts_job_attempt ON job_attempts(job_id, attempt);
    CREATE INDEX IF NOT EXISTS idx_job_events_job_created ON job_events(job_id, created_at);
    """),
    (4, """
    CREATE TABLE IF NOT EXISTS telegram_operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operation_id TEXT NOT NULL,
        timestamp REAL NOT NULL,
        method TEXT NOT NULL,
        peer_id TEXT,
        operation_class TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        result_classification TEXT NOT NULL,
        latency_ms REAL NOT NULL,
        flood_wait_seconds REAL,
        slow_mode_seconds REAL,
        peer_flood INTEGER NOT NULL DEFAULT 0,
        error_class TEXT,
        retry_count INTEGER NOT NULL DEFAULT 0,
        payload_size INTEGER,
        job_id TEXT,
        source TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_telegram_operations_timestamp ON telegram_operations(timestamp DESC, id DESC);
    CREATE INDEX IF NOT EXISTS idx_telegram_operations_method ON telegram_operations(method, timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_telegram_operations_peer ON telegram_operations(peer_id, timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_telegram_operations_result ON telegram_operations(result_classification, timestamp DESC);
    """),
    (5, """
    CREATE TABLE IF NOT EXISTS telegram_entities (
        lookup_key TEXT PRIMARY KEY,
        entity_id INTEGER,
        access_hash INTEGER,
        username TEXT,
        title TEXT,
        first_name TEXT,
        last_name TEXT,
        entity_type TEXT NOT NULL,
        last_seen REAL NOT NULL,
        photo_id TEXT,
        capabilities_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_telegram_entities_seen ON telegram_entities(last_seen DESC);
    CREATE INDEX IF NOT EXISTS idx_telegram_entities_id ON telegram_entities(entity_id);
    CREATE INDEX IF NOT EXISTS idx_telegram_entities_username ON telegram_entities(username);
    CREATE TABLE IF NOT EXISTS telegram_dialogs (
        peer_key TEXT PRIMARY KEY,
        dialog_type TEXT NOT NULL,
        title TEXT,
        username TEXT,
        last_message_id INTEGER,
        last_sync_at REAL NOT NULL,
        sync_state TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_telegram_dialogs_sync ON telegram_dialogs(last_sync_at DESC);
    CREATE INDEX IF NOT EXISTS idx_telegram_dialogs_username ON telegram_dialogs(username);
    """),
    (6, """
    CREATE TABLE IF NOT EXISTS telegram_latest_messages (
        message_id INTEGER NOT NULL,
        source_peer TEXT,
        event_id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        entity_id INTEGER,
        payload_json TEXT NOT NULL,
        observed_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_tg_latest_message_key ON telegram_latest_messages(source_peer, message_id);
    CREATE TABLE IF NOT EXISTS telegram_entity_observations (
        event_id TEXT PRIMARY KEY,
        entity_id INTEGER,
        source_peer TEXT,
        event_type TEXT NOT NULL,
        observed_at REAL NOT NULL,
        payload_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_tg_entity_obs_entity_time ON telegram_entity_observations(entity_id, observed_at DESC);
    CREATE TABLE IF NOT EXISTS telegram_timeline (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE,
        event_type TEXT NOT NULL,
        source_peer TEXT,
        entity_id INTEGER,
        message_id INTEGER,
        observed_at REAL NOT NULL,
        payload_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_tg_timeline_peer_time ON telegram_timeline(source_peer, observed_at DESC);
    CREATE INDEX IF NOT EXISTS idx_tg_timeline_entity_time ON telegram_timeline(entity_id, observed_at DESC);
    """),
    (7, """
    CREATE TABLE IF NOT EXISTS intel_sources (
        source_id TEXT PRIMARY KEY,
        source_family TEXT NOT NULL,
        provider TEXT NOT NULL,
        dataset_id TEXT,
        dataset_version TEXT,
        source_type TEXT NOT NULL,
        uri TEXT,
        lineage_class TEXT NOT NULL DEFAULT 'UNKNOWN',
        lineage_confidence REAL NOT NULL DEFAULT 0,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS intel_entities (
        entity_id TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        canonical_value TEXT NOT NULL,
        display_value TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_intel_entity_canonical ON intel_entities(entity_type, canonical_value);
    CREATE TABLE IF NOT EXISTS intel_observations (
        observation_id TEXT PRIMARY KEY,
        entity_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_family TEXT NOT NULL,
        source_dataset TEXT,
        source_version TEXT,
        retrieved_at REAL NOT NULL,
        observed_at REAL,
        query_context TEXT,
        matched_field TEXT,
        match_type TEXT,
        evidence_state TEXT NOT NULL DEFAULT 'OBSERVED',
        confidence REAL NOT NULL DEFAULT 0,
        provenance_json TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY(entity_id) REFERENCES intel_entities(entity_id) ON DELETE CASCADE,
        FOREIGN KEY(source_id) REFERENCES intel_sources(source_id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_intel_obs_entity_time ON intel_observations(entity_id, observed_at DESC, retrieved_at DESC);
    CREATE INDEX IF NOT EXISTS idx_intel_obs_source_time ON intel_observations(source_id, retrieved_at DESC);
    CREATE TABLE IF NOT EXISTS intel_relationships (
        relationship_id TEXT PRIMARY KEY,
        from_entity_id TEXT NOT NULL,
        relationship_type TEXT NOT NULL,
        to_entity_id TEXT NOT NULL,
        evidence_state TEXT NOT NULL DEFAULT 'CORRELATED',
        confidence REAL NOT NULL DEFAULT 0,
        observation_id TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        FOREIGN KEY(from_entity_id) REFERENCES intel_entities(entity_id) ON DELETE CASCADE,
        FOREIGN KEY(to_entity_id) REFERENCES intel_entities(entity_id) ON DELETE CASCADE,
        FOREIGN KEY(observation_id) REFERENCES intel_observations(observation_id) ON DELETE SET NULL
    );
    CREATE INDEX IF NOT EXISTS idx_intel_rel_from ON intel_relationships(from_entity_id, relationship_type);
    CREATE INDEX IF NOT EXISTS idx_intel_rel_to ON intel_relationships(to_entity_id, relationship_type);
    """),
    (8, """
    CREATE TABLE IF NOT EXISTS telegram_replay_runs (
        run_id TEXT PRIMARY KEY,
        projection TEXT NOT NULL,
        state TEXT NOT NULL,
        cursor_id INTEGER NOT NULL DEFAULT 0,
        processed_count INTEGER NOT NULL DEFAULT 0,
        started_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        last_error TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_telegram_replay_state ON telegram_replay_runs(state, updated_at DESC);
    """),
)


class StorageError(RuntimeError):
    pass


class StorageService:
    """Own the canonical platform database and deterministic migration lifecycle."""

    BUSY_TIMEOUT_MS = 5000
    BACKUP_TIMEOUT_SECONDS = 30.0
    MAX_BACKUP_BYTES = 2 * 1024 * 1024 * 1024

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.path = self.project_root / "data" / "databases" / "platform.db"
        self.conn: aiosqlite.Connection | None = None
        self.lock = asyncio.Lock()
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.conn = await aiosqlite.connect(self.path)
            self.conn.row_factory = aiosqlite.Row
            await self.conn.execute("PRAGMA journal_mode=WAL")
            await self.conn.execute("PRAGMA synchronous=NORMAL")
            await self.conn.execute("PRAGMA foreign_keys=ON")
            await self.conn.execute(f"PRAGMA busy_timeout={self.BUSY_TIMEOUT_MS}")
            await self.conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at REAL NOT NULL)")
            await self.conn.commit()
            await self._migrate()
            if not await self.integrity_check():
                raise StorageError("Platform database integrity check failed after startup")
            self._started = True
        except StorageError:
            conn, self.conn = self.conn, None
            if conn is not None:
                await conn.close()
            raise
        except (sqlite3.Error, OSError) as exc:
            conn, self.conn = self.conn, None
            if conn is not None:
                await conn.close()
            raise StorageError(f"Unable to initialize platform database: {exc}") from exc

    async def _migrate(self) -> None:
        assert self.conn is not None
        for version, sql in MIGRATIONS:
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            try:
                await self.conn.execute("BEGIN IMMEDIATE")
                async with self.conn.execute("SELECT checksum FROM schema_migrations WHERE version=?", (version,)) as cursor:
                    row = await cursor.fetchone()
                if row is not None:
                    if row[0] != checksum:
                        raise StorageError(f"Migration checksum mismatch: {version}")
                    await self.conn.commit()
                    continue
                for statement in (part.strip() for part in sql.split(";") if part.strip()):
                    await self.conn.execute(statement)
                await self.conn.execute("INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (?, ?, ?)", (version, checksum, time.time()))
                await self.conn.commit()
            except Exception:
                await self.conn.rollback()
                raise

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Cursor:
        if self.conn is None:
            raise StorageError("StorageService is not started")
        async with self.lock:
            try:
                cursor = await self.conn.execute(sql, params)
                await self.conn.commit()
                return cursor
            except sqlite3.Error as exc:
                await self.conn.rollback()
                raise StorageError(f"Database write failed: {exc}") from exc

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        if self.conn is None:
            raise StorageError("StorageService is not started")
        async with self.lock:
            try:
                async with self.conn.execute(sql, params) as cursor:
                    return await cursor.fetchone()
            except sqlite3.Error as exc:
                raise StorageError(f"Database read failed: {exc}") from exc

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        if self.conn is None:
            raise StorageError("StorageService is not started")
        async with self.lock:
            try:
                async with self.conn.execute(sql, params) as cursor:
                    return await cursor.fetchall()
            except sqlite3.Error as exc:
                raise StorageError(f"Database read failed: {exc}") from exc

    async def transaction(self, statements: list[tuple[str, tuple[Any, ...]]]) -> None:
        if self.conn is None:
            raise StorageError("StorageService is not started")
        async with self.lock:
            try:
                await self.conn.execute("BEGIN")
                for sql, params in statements:
                    await self.conn.execute(sql, params)
                await self.conn.commit()
            except sqlite3.Error as exc:
                await self.conn.rollback()
                raise StorageError(f"Database transaction failed: {exc}") from exc

    async def integrity_check(self) -> bool:
        row = await self.fetchone("PRAGMA integrity_check")
        return bool(row and str(row[0]).lower() == "ok")

    async def foreign_key_check(self) -> list[sqlite3.Row]:
        return await self.fetchall("PRAGMA foreign_key_check")

    async def fts_consistency(self) -> dict[str, int | bool]:
        documents = await self.fetchone("SELECT COUNT(*) FROM search_documents")
        fts_rows = await self.fetchone("SELECT COUNT(*) FROM search_fts")
        orphan_fts = await self.fetchone("SELECT COUNT(*) FROM search_fts f LEFT JOIN search_documents d ON d.id=f.id WHERE d.id IS NULL")
        missing_fts = await self.fetchone("SELECT COUNT(*) FROM search_documents d LEFT JOIN search_fts f ON f.id=d.id WHERE f.id IS NULL")
        result = {"documents": int(documents[0]) if documents else 0, "fts_rows": int(fts_rows[0]) if fts_rows else 0, "orphan_fts": int(orphan_fts[0]) if orphan_fts else 0, "missing_fts": int(missing_fts[0]) if missing_fts else 0}
        result["consistent"] = result["orphan_fts"] == 0 and result["missing_fts"] == 0 and result["documents"] == result["fts_rows"]
        return result

    async def database_size(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            try:
                total += candidate.stat().st_size
            except FileNotFoundError:
                pass
        return total

    async def checkpoint(self, *, truncate: bool = False) -> None:
        if self.conn is None:
            raise StorageError("StorageService is not started")
        mode = "TRUNCATE" if truncate else "PASSIVE"
        async with self.lock:
            try:
                await self.conn.execute(f"PRAGMA wal_checkpoint({mode})")
            except sqlite3.Error as exc:
                raise StorageError(f"WAL checkpoint failed: {exc}") from exc

    async def backup(self, destination: str | Path) -> Path:
        if self.conn is None:
            raise StorageError("StorageService is not started")
        target = Path(destination).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target == self.path:
            raise StorageError("Backup destination must differ from source")
        if await self.database_size() > self.MAX_BACKUP_BYTES:
            raise StorageError("Database exceeds configured backup size bound")
        if not await self.integrity_check():
            raise StorageError("Refusing backup of an integrity-failed database")
        temp_path: Path | None = None
        async with self.lock:
            try:
                fd, raw_temp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
                os.close(fd)
                temp_path = Path(raw_temp)
                target_conn = sqlite3.connect(temp_path)
                try:
                    await self.conn.commit()
                    await asyncio.wait_for(self.conn.backup(target_conn), timeout=self.BACKUP_TIMEOUT_SECONDS)
                    target_conn.commit()
                    check = target_conn.execute("PRAGMA integrity_check").fetchone()
                    if not check or str(check[0]).lower() != "ok":
                        raise StorageError("Backup integrity check failed")
                finally:
                    target_conn.close()
                os.replace(temp_path, target)
                temp_path = None
                return target
            except (sqlite3.Error, asyncio.TimeoutError, OSError) as exc:
                raise StorageError(f"Database backup failed: {exc}") from exc
            finally:
                if temp_path is not None:
                    try:
                        temp_path.unlink()
                    except FileNotFoundError:
                        pass

    async def restore(self, backup: str | Path) -> None:
        if self._started or self.conn is not None:
            raise StorageError("Restore requires a stopped StorageService")
        source = Path(backup).resolve()
        if not source.is_file() or source == self.path:
            raise StorageError("Invalid restore source")
        if source.stat().st_size > self.MAX_BACKUP_BYTES:
            raise StorageError("Restore source exceeds configured database size bound")
        source_conn = sqlite3.connect(source)
        try:
            check = source_conn.execute("PRAGMA integrity_check").fetchone()
            if not check or str(check[0]).lower() != "ok":
                raise StorageError("Refusing restore from an integrity-failed backup")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, raw_temp = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".restore", dir=self.path.parent)
            os.close(fd)
            temp = Path(raw_temp)
            try:
                target_conn = sqlite3.connect(temp)
                try:
                    source_conn.backup(target_conn)
                    target_conn.commit()
                    check = target_conn.execute("PRAGMA integrity_check").fetchone()
                    if not check or str(check[0]).lower() != "ok":
                        raise StorageError("Restored database integrity check failed")
                finally:
                    target_conn.close()
                os.replace(temp, self.path)
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(str(self.path) + suffix)
                    try:
                        sidecar.unlink()
                    except FileNotFoundError:
                        pass
            finally:
                try:
                    temp.unlink()
                except FileNotFoundError:
                    pass
        except sqlite3.Error as exc:
            raise StorageError(f"Database restore failed: {exc}") from exc
        finally:
            source_conn.close()

    async def close(self) -> None:
        if self.conn is None:
            self._started = False
            return
        async with self.lock:
            conn, self.conn = self.conn, None
            try:
                await conn.execute("PRAGMA optimize")
                await conn.close()
            finally:
                self._started = False
