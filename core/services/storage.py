"""Canonical platform SQLite storage and deterministic migrations."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
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
)


class StorageError(RuntimeError):
    pass


class StorageService:
    """Own the canonical platform database and deterministic migration lifecycle."""

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
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA synchronous=NORMAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.execute("PRAGMA busy_timeout=5000")
        await self.conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at REAL NOT NULL)")
        await self.conn.commit()
        await self._migrate()
        self._started = True

    async def _migrate(self) -> None:
        assert self.conn is not None
        for version, sql in MIGRATIONS:
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            async with self.conn.execute("SELECT checksum FROM schema_migrations WHERE version=?", (version,)) as cursor:
                row = await cursor.fetchone()
            if row is not None:
                if row[0] != checksum:
                    raise StorageError(f"Migration checksum mismatch: {version}")
                continue
            try:
                await self.conn.execute("BEGIN")
                for statement in (part.strip() for part in sql.split(";") if part.strip()):
                    await self.conn.execute(statement)
                await self.conn.execute("INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (?, ?, strftime('%s','now'))", (version, checksum))
                await self.conn.commit()
            except Exception:
                await self.conn.rollback()
                raise

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Cursor:
        if self.conn is None:
            raise StorageError("StorageService is not started")
        async with self.lock:
            cursor = await self.conn.execute(sql, params)
            await self.conn.commit()
            return cursor

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        if self.conn is None:
            raise StorageError("StorageService is not started")
        async with self.lock:
            async with self.conn.execute(sql, params) as cursor:
                return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        if self.conn is None:
            raise StorageError("StorageService is not started")
        async with self.lock:
            async with self.conn.execute(sql, params) as cursor:
                return await cursor.fetchall()

    async def transaction(self, statements: list[tuple[str, tuple[Any, ...]]]) -> None:
        if self.conn is None:
            raise StorageError("StorageService is not started")
        async with self.lock:
            try:
                await self.conn.execute("BEGIN")
                for sql, params in statements:
                    await self.conn.execute(sql, params)
                await self.conn.commit()
            except Exception:
                await self.conn.rollback()
                raise

    async def integrity_check(self) -> bool:
        row = await self.fetchone("PRAGMA integrity_check")
        return bool(row and row[0] == "ok")

    async def backup(self, destination: str | Path) -> Path:
        if self.conn is None:
            raise StorageError("StorageService is not started")
        target = Path(destination).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target == self.path:
            raise StorageError("Backup destination must differ from source")
        await self.conn.commit()
        target_conn = sqlite3.connect(target)
        try:
            await self.conn.backup(target_conn)
        finally:
            target_conn.close()
        return target

    async def close(self) -> None:
        if self.conn is None:
            return
        async with self.lock:
            conn, self.conn = self.conn, None
            await conn.execute("PRAGMA optimize")
            await conn.close()
        self._started = False
